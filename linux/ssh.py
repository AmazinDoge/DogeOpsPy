import base64
import re
import time

import paramiko
import os
import os.path as p

# Author DevOpsDoge

# # Use SSH class in a context manager
# with BastionJumpSSH(
#         bastion_ip=bastion_cfg["ip"],
#         bastion_user=bastion_cfg["user"],
#         key_path=bastion_cfg["key"],
#         target_ip=target_ip,
#         target_user=target_user
# ) as conn:
#     print(conn.exec("whoami"))
#     print(conn.exec("sudo docker ps -a"))
#     print(conn.exec("sudo docker ps -a"))
#     print(conn.exec("sudo docker ps -a"))
#     print(conn.exec("sudo docker ps -a"))

class BastionJumpSSH:
    END=">><END><<"
    def __init__(self, bastion_ip, bastion_user, key_path, target_ip, target_user, timeout=10):
        self.bastion_ip = bastion_ip
        self.bastion_user = bastion_user
        self.key_path = os.path.expanduser(key_path)
        self.target_ip = target_ip
        self.target_user = target_user
        self.timeout = timeout

        self.ssh = None
        self.channel = None

    def __enter__(self):
        # Connect to bastion
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            hostname=self.bastion_ip,
            username=self.bastion_user,
            key_filename=self.key_path
        )

        # Open shell and ssh to target
        self.channel = self.ssh.invoke_shell()
        self.ssh_init()

        self.channel.send(f"ssh -o StrictHostKeyChecking=no {self.target_user}@{self.target_ip}\n")
        output = self._read(stop_endswith="$")

        if "yes/no" in output:
            self.channel.send("yes\n")
            output = self._read()

        if "Permission denied" in output:
            raise Exception("SSH to target failed: permission denied")

        self.ssh_init()

        return self

    @staticmethod
    def strip_ansi_sequences(s):
        # Remove ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', s)

    def ssh_init(self):
        self.channel.send(f'export PS1="{self.END}"\n')
        self._read()

    def exec(self, command):
        self.channel.send(command + "\n")
        result = self.strip_ansi_sequences(self._read())
        if result.startswith(command):
            result = result[len(command):]
            result = result.lstrip()
        return result

    def write_file(self, file_path, muti_lines_str, permission_number="644"):
        file_path = p.normpath(file_path)
        file_dirname = p.dirname(file_path)
        result = list()
        result.append(self.exec(f"mkdir -p {file_dirname}"))
        muti_lines_str_b64 = base64.b64encode(muti_lines_str.encode()).decode()
        result.append(self.exec(f"echo '{muti_lines_str_b64}' | base64 -d > {file_path}"))
        result.append(self.exec(f"chmod {permission_number} {file_path}"))
        return result

    def _read(self, timeout=5, stop_endswith=""):
        buffer = bytearray()
        last_active = time.time()

        while True:
            if self.channel.recv_ready():
                chunk = self.channel.recv(4096)
                buffer.extend(chunk)
                last_active = time.time()  # 每次收到数据就刷新耐心
            else:
                decoded = buffer.decode("utf-8", errors="replace").rstrip()
                if self.END in decoded:
                    break
                if stop_endswith and decoded.endswith(stop_endswith):
                    break
                if time.time() - last_active > timeout:
                    break

                time.sleep(0.1)

        # Removal of last line
        if decoded.split("\n")[-1].endswith(stop_endswith):
            decoded = "\n".join(decoded.split("\n")[:-1])

        return decoded

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.channel:
            self.channel.close()
        if self.ssh:
            self.ssh.close()
