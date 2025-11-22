import base64
import re
import sys
import time

import paramiko
import os
import os.path as p

ERROR_TAG = "!==DOGE_SSH_EXEC_ERROR==!\n"

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
    def __init__(self, bastion_ip, bastion_user, key_path, target_ip, target_user, timeout=None, mute_warnings=False):
        self.bastion_ip = bastion_ip
        self.bastion_user = bastion_user
        self.key_path = os.path.expanduser(key_path)
        self.target_ip = target_ip
        self.target_user = target_user
        self.timeout = timeout
        self.mute_warnings = mute_warnings

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
        self._read(mute_warnings=True)

    def exec(self, command, timeout_override=None):
        timeout = timeout_override if timeout_override else self.timeout
        self.channel.send(command + "\n")
        result = self.strip_ansi_sequences(self._read(timeout=timeout))
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

    def _read(self, timeout=None, timeout_raise=True, stop_endswith="", mute_warnings=False):
        buffer = bytearray()
        last_active = time.time()

        stop_endswith = self.END if not stop_endswith else stop_endswith
        while True:
            if self.channel.recv_ready():
                chunk = self.channel.recv(4096)
                buffer.extend(chunk)
                last_active = time.time()  # 每次收到数据就刷新耐心
            else:
                decoded = buffer.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip()
                if decoded.endswith(stop_endswith):
                    break
                if timeout is not None and 0 < timeout < time.time() - last_active:
                    if timeout_raise:
                        if stop_endswith in decoded and not mute_warnings:
                            print(f"_read() buffer contains {decoded.count(stop_endswith)} EndSymbol but not endswith any of them, hence timeout.", file=sys.stderr)
                        raise TimeoutError(f"_read() timeout in {timeout}, consider use drain() to clear")
                    else:
                        break

                time.sleep(0.1)

        # Get last reply
        replies = [reply.rstrip() for reply in decoded.split(stop_endswith) if reply.strip()]
        if len(replies) > 1 and not mute_warnings:
            print(f"_read() get {len(replies)} replies, last query could be TimeOut, will only return last reply", file=sys.stderr)
            for idx, reply in enumerate(replies):
                print(idx, reply.replace("\n", "</br>"), file=sys.stderr)

        return replies[-1]

    def drain(self, timeout=10):
        try:
            self._read(timeout=timeout, mute_warnings=True)
        except TimeoutError:
            return False
        return True

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.channel:
            self.channel.close()
        if self.ssh:
            self.ssh.close()

# =====================================用法===================================
# from ssh import DirectSSH, ERROR_TAG
# import os
#
# TARGET_HOST = "45.118.134.177"
# TARGET_USER = "aox"
# TARGET_KEY = "~/.ssh/id_ed25519"
# TIMEOUT = 3
# with DirectSSH(
#     host=TARGET_HOST,
#     user=TARGET_USER,
#     key_path=TARGET_KEY,
#     timeout=TIMEOUT,
# ) as conn:
#     # CMD
#     print(conn.exec("whoami"))
#     print(ERROR_TAG in conn.exec("bad cmd can't execute"))
#
#     # File Transfer
#     local_file = os.path.expanduser("~/Downloads/get-pip.py")
#     remote_file = "/home/aox/uploaded_file"
#     with open(local_file, "r", encoding="utf-8") as f:
#         content = f.read()
#     conn.write_file(remote_file, content)
#
#     # Timeout
#     conn.exec(command="sleep 4", timeout=TIMEOUT)


class DirectSSH:
    def __init__(self, host, user, key_path=None, password=None, port=22, timeout=10):
        self.host = host
        self.user = user
        self.key_path = os.path.expanduser(key_path) if key_path else None
        self.password = password
        self.port = port
        self.timeout = timeout
        self.ssh = None

    def __enter__(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            hostname=self.host,
            port=self.port,
            username=self.user,
            key_filename=self.key_path,
            password=self.password,
            timeout=self.timeout,
        )
        return self

    def exec(self, command, timeout=10):
        stdin, stdout, stderr = self.ssh.exec_command(command)
        stdout.channel.settimeout(timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if err:
            out += f"{ERROR_TAG}{err}"
        return out

    def write_file(self, remote_path, content, permission="644"):
        sftp = self.ssh.open_sftp()
        try:
            # 确保目录存在可以用 exec("mkdir -p ...")，SFTP 本身没 mkdir -p
            dir_path = os.path.dirname(remote_path)
            if dir_path:
                self.exec(f"mkdir -p '{dir_path}'")

            with sftp.file(remote_path, "w") as f:
                f.write(content)
            sftp.chmod(remote_path, int(permission, 8))
        finally:
            sftp.close()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.ssh:
            self.ssh.close()
