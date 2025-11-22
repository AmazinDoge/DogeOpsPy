import re

def escape_comments(line):
    in_single = in_double = False
    for i, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == '#' and not in_single and not in_double:
            return line[:i].rstrip()
    return line.rstrip()

# THIS IS PARSING NGINX -T WITH LOTS OF GARBAGE
def T_to_conf(T_result):
    result_lines = []
    proper_T_magic_word = "syntax is ok"
    prev_line = ""

    if proper_T_magic_word in T_result:
        T_result = T_result.split(proper_T_magic_word, 1)[1]  # Trash everything before magic word.
        T_result = re.sub(
            r'nginx: configuration file \S+ test (?:failed|is successful)',
            '',
            T_result
        )
        for line in T_result.split("\n"):
            uncommented = escape_comments(line)
            if uncommented.strip() == "" and prev_line.strip() == "":
                continue  # No 2 lines are all blanks
            result_lines.append(uncommented)
            prev_line = uncommented

    return result_lines

def conf_to_upstream_dict(conf_lines):
    # 压扁，用正则处理, 输入绝对不可以有注释！
    conf_text = " ".join(conf_lines).replace("\n", " ")

    # upstream 空格+ （非空格）空格* 「 （里面裹的一切）」
    upstream_blocks = re.findall(r"upstream\s+(\S+)\s*\{(.*?)\}", conf_text)

    upstreams = {}
    for name, block_body in upstream_blocks:
        # server 空格+ （累计所有字符直到发现空格或;）
        # server abc.com:30000;
        # server 1.1.1.1:3000 weight=2 max_fails=3 fail_timeout=30s;
        servers = re.findall(r"server\s+([^\s;]+)", block_body)
        upstreams[name] = servers

    return upstreams


def conf_to_server_dicts(conf_lines):
    upstreams_dict = conf_to_upstream_dict(conf_lines)
    server_blocks = conf_to_server_block_lines(conf_lines)
    result = []

    for block_lines in server_blocks:
        server_data = {
            "listen": {},
            "ssl": "",
            "proxy_protocol": False,
            "proxy": [],
            "l7": []
        }

        block_text = " ".join(block_lines)

        # === LISTEN ===
        for match in re.finditer(r"listen\s+([^\s;]+)([^;]*);", block_text):
            listen_target = match.group(1).strip()
            flags = match.group(2).strip()
            server_data["listen"][listen_target] = flags

        server_data["listen"] = dict(sorted(server_data["listen"].items()))

        # === SSL ===
        cert = re.search(r"ssl_certificate\s+([^\s;]+);", block_text)
        key = re.search(r"ssl_certificate_key\s+([^\s;]+);", block_text)
        ssl_params = []
        if cert:
            ssl_params.append(cert.group(1))
        if key:
            ssl_params.append(key.group(1))
        server_data["ssl"] = ";".join(ssl_params)

        # === PROXY_PROTOCOL ===
        if re.search(r"\bproxy_protocol\s+on;", block_text):
            server_data["proxy_protocol"] = True

        # === PROXY_PASS ===
        for match in re.finditer(r"proxy_pass\s+(.*?);", block_text):
            target = match.group(1).strip().strip('"').strip("'")
            lookup_key = target.lower() if "://" not in target and not target.startswith("unix:") else target
            if lookup_key in upstreams_dict:
                server_data["proxy"].extend(upstreams_dict[lookup_key])
            else:
                server_data["proxy"].append(target)

        # === L7 location paths ===
        for match in re.finditer(r"location\s+([^{\s]+)", block_text):
            server_data["l7"].append(match.group(1).strip())

        result.append(server_data)

    return result


def conf_to_server_block_lines(conf_lines):
    server_blocks = []
    inside_block = False
    brace_stack = 0
    current_block = []

    for raw_line in conf_lines:
        line = raw_line.strip()
        # Skip empty lines
        if not line:
            continue

        # Search for 'server {', allowing arbitrary spacing
        match = re.search(r'\bserver\s*\{', line)
        if match:
            # Start of new server block
            inside_block = True
            brace_stack = 0
            # Strip everything before 'server {'
            start_index = match.start()
            line = line[start_index:]
            current_block = []

        if inside_block:
            current_block.append(line)
            # Count braces
            brace_stack += line.count('{')
            brace_stack -= line.count('}')
            if brace_stack == 0:
                # Completed one full server block
                server_blocks.append(current_block)
                inside_block = False
                current_block = []

    return server_blocks

