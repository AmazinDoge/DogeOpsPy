import json
import re
import traceback

def docker_inspect_to_envoy_config_path(inspect_str):
    envoy_config_path = ""
    try:
        inspect_obj = json.loads(inspect_str)
        if not inspect_obj or not isinstance(inspect_obj, list):
            raise ValueError("Unexpected JSON structure")

        container = inspect_obj[0]  # Should be only one in list
        config = container.get("Config", {})
        path = container.get("Path", "")
        args = container.get("Args", [])
        cmd = config.get("Cmd", [])

        # Prioritize actual running command
        if path and args:
            full_cmd = [path] + args
        else:
            full_cmd = cmd

        cmdline = " ".join(full_cmd)

        # Regex match yaml/yml path (non-greedy, allows quoting)
        match = re.search(r"(/\S+\.(yaml|yml))", cmdline)
        if match:
            envoy_config_path = match.group(1)

    except Exception:
        print(f"docker_inspect_to_envoy_config_path FAULT: {traceback.format_exc()}")

    return envoy_config_path

def conf_to_clusters(envoy_config):
    clusters = {}
    try:
        cluster_list = envoy_config.get("static_resources", {}).get("clusters", [])
        if cluster_list:
            for cluster in cluster_list:
                name = cluster.get("name")
                addresses = []
                for endpoint in cluster.get("load_assignment", {}).get("endpoints", []):
                    for lb in endpoint.get("lb_endpoints", []):
                        addr_info = lb.get("endpoint", {}).get("address", {}).get("socket_address", {})
                        address = addr_info.get("address")
                        port = addr_info.get("port_value")
                        if address and port:
                            addresses.append(f"{address}:{port}")
                clusters[name] = addresses
    except Exception as e:
        clusters["__error__"] = str(e)
        print("Fail to get clusters")
        print(traceback.format_exc())
    return clusters

def conf_to_server_dicts(conf_dict):
    if not isinstance(conf_dict, dict):
        raise ValueError("conf_to_server_dicts takes a yaml.safe_load() dict!!!")

    output = []

    # Get clusters once
    clusters = conf_to_clusters(conf_dict)

    # Get listeners from static_resources
    listeners = conf_dict.get("static_resources", {}).get("listeners", [])

    if not listeners:
        return output

    for listener in listeners:
        listen_entry = {}

        # Step 1: Ports & Address (IPv4 / IPv6 distinction)
        socket_address = (
            listener.get("address", {})
                    .get("socket_address", {})
        )
        ip = socket_address.get("address", "0.0.0.0")
        port = str(socket_address.get("port_value", 0))
        if ":" in ip and not ip.startswith("["):
            key = f"[{ip}]:{port}"
        else:
            key = f"{ip}:{port}"

        listen_entry["listen"] = {key: ""}

        # Step 2: SSL detection
        ssl_paths = []
        filter_chains = listener.get("filter_chains", [])
        if not filter_chains:
            continue

        for chain in filter_chains:
            tls = chain.get("transport_socket", {}).get("typed_config", {})
            if isinstance(tls, dict):
                certs = tls.get("common_tls_context", {}).get("tls_certificates", [])
                if not certs:
                    continue
                for cert in certs:
                    crt = cert.get("certificate_chain", {}).get("filename")
                    if crt:
                        ssl_paths.append(str(crt))
                    keyfile = cert.get("private_key", {}).get("filename")
                    if keyfile:
                        ssl_paths.append(str(keyfile))
        listen_entry["ssl"] = ";".join(ssl_paths)

        # Step 3: Proxy Protocol (correct detection from listener_filters)
        listener_filters = listener.get("listener_filters", [])
        listen_entry["proxy_protocol"] = any(
            "proxy_protocol" in f.get("name", "")
            for f in listener_filters
        )

        clusters_used = set()

        # Step 4: Route (cluster usage + l7 path)
        l7_routes = []
        for chain in filter_chains:
            for f in chain.get("filters", []):
                if "http_connection_manager" not in f.get("name"):
                    continue
                route_config = f.get("typed_config", {}).get("route_config", {})
                virtual_hosts = route_config.get("virtual_hosts", [])
                for vh in virtual_hosts:
                    for domain in vh.get("domains", []):
                        for route in vh.get("routes", []):
                            match = route.get("match", {})
                            prefix = match.get("prefix", "/")
                            l7_routes.append(f"{domain}{prefix}")
                            cluster_name = route.get("route", {}).get("cluster")
                            if cluster_name:
                                clusters_used.add(cluster_name)

        # Step 5: Detect L4 TCP proxy usage
        l4_proxies = []
        for chain in filter_chains:
            for f in chain.get("filters", []):
                if "tcp_proxy" in f.get("name", ""):
                    tcp_config = f.get("typed_config", {})
                    cluster_name = tcp_config.get("cluster")
                    if cluster_name:
                        clusters_used.add(cluster_name)
                        l4_proxies.append({
                            "listener_port": listener.get("address", {}).get("socket_address", {}).get("port_value"),
                            "cluster": cluster_name,
                        })


        # Step 6: Map cluster names to IP:Port
        proxy_targets = []
        for cluster in clusters_used:
            resolved = clusters.get(cluster)
            if resolved:
                proxy_targets.extend(resolved)
            else:
                proxy_targets.append(cluster)

        listen_entry["proxy"] = proxy_targets
        listen_entry["l7"] = l7_routes

        # Final touch: annotate listen type
        if ssl_paths:
            for k in listen_entry["listen"]:
                listen_entry["listen"][k] = "ssl"
        else:
            for k in listen_entry["listen"]:
                listen_entry["listen"][k] = "default_server"

        output.append(listen_entry)

    return output
