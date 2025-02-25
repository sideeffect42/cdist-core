# -*- coding: utf-8 -*-
#
# 2011-2017 Steven Armstrong (steven-cdist at armstrong.cc)
# 2011-2013 Nico Schottelius (nico-cdist at schottelius.org)
# 2022,2023,2025 Dennis Camera (dennis.camera at riiengineering.ch)
#
# This file is part of cdist.
#
# cdist is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cdist is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with cdist. If not, see <http://www.gnu.org/licenses/>.
#

import glob
import os
import stat
import subprocess

import cdist
import cdist.log

from cdist.exec import util
from cdist.util import (ipaddr, shquot)


def _wrap_addr(addr):
    """If addr is IPv6 then return addr wrapped between '[' and ']',
    otherwise return it unchanged."""
    if ipaddr.is_ipv6(addr):
        return "[%s]" % addr
    else:
        return addr


class DecodeError(cdist.Error):
    def __init__(self, command):
        self.command = command

    def __str__(self):
        return "Cannot decode output of " + " ".join(self.command)


class Remote:
    """Execute commands remotely.

    All interaction with the target should be done through this class.
    Directly accessing the target from Python code is a bug!
    """
    def __init__(self,
                 target_host,
                 remote_exec,
                 base_path,
                 settings,
                 stdout_base_path=None,
                 stderr_base_path=None):
        self.target_host = target_host
        self._exec = shquot.split(remote_exec)

        self.archiving_mode = settings.archiving_mode
        self.base_path = base_path
        self.settings = settings

        self.stdout_base_path = stdout_base_path
        self.stderr_base_path = stderr_base_path

        self.conf_path = os.path.join(self.base_path, "conf")
        self.object_path = os.path.join(self.base_path, "object")

        self.type_path = os.path.join(self.conf_path, "type")
        self.global_explorer_path = os.path.join(self.conf_path, "explorer")

        self._open_logger()

        self._init_env()

    def _open_logger(self):
        self.log = cdist.log.getLogger(self.target_host[0])

    # logger is not pickable, so remove it when we pickle
    def __getstate__(self):
        state = self.__dict__.copy()
        if 'log' in state:
            del state['log']
        return state

    # recreate logger when we unpickle
    def __setstate__(self, state):
        self.__dict__.update(state)
        self._open_logger()

    def _init_env(self):
        """Setup environment for scripts."""
        # FIXME: better do so in exec functions that require it!
        os.environ['__remote_exec'] = shquot.join(self._exec)

    def create_files_dirs(self):
        self.rmdir(self.base_path)
        self.mkdir(self.base_path, umask=0o077)
        self.mkdir(self.conf_path)

    def remove_files_dirs(self):
        self.rmdir(self.base_path)

    def rmfile(self, path):
        """Remove file on the target."""
        self.log.trace("Remote rm: %s", path)
        self.run(["rm", "-f",  path])

    def rmdir(self, path):
        """Remove directory on the target."""
        self.log.trace("Remote rmdir: %s", path)
        self.run(["rm", "-r", "-f",  path])

    def mkdir(self, path, umask=None):
        """Create directory on the target."""
        self.log.trace("Remote mkdir: %s", path)

        cmd = "mkdir -p %s" % (shquot.quote(path),)
        if umask is not None:
            mode = (0o777 & ~umask)
            cmd = "umask %04o; %s && chmod %o %s" % (
                umask, cmd, mode, shquot.quote(path))

        self.run(cmd)

    def extract_archive(self, path, mode):
        """Extract archive path on the target."""
        import cdist.autil as autil

        self.log.trace("Remote extract archive: %s", path)
        # AIX only allows -C at the end
        command = [
            "tar",
            "-x",
            "-f", path,
            "-C", os.path.dirname(path)
        ]
        if mode is not None:
            command += mode.extract_opts
        self.run(command)

    def _transfer_file(self, source, destination, umask=None):
        remote_cmd = "cat >%s" % (shquot.quote(destination),)
        if umask is not None:
            mode = (stat.S_IMODE(os.stat(source).st_mode) & ~umask)
            remote_cmd = "umask %04o; %s && chmod %o %s" % (
                umask, remote_cmd, mode, shquot.quote(destination))

        command = self._exec + [self.target_host[0], remote_cmd]
        with open(source, "r") as f:
            self._run_command(command, stdin=f)

    def transfer(self, source, destination, jobs=None, umask=None):
        """Transfer a file or directory to the target."""
        self.log.trace("Remote transfer: %s -> %s", source, destination)
        # self.rmdir(destination)
        if os.path.isdir(source):
            self.mkdir(destination, umask=umask)
            used_archiving = False
            if self.archiving_mode is not None:
                self.log.trace("Remote transfer in archiving mode")
                import cdist.autil as autil

                # create archive
                tarpath, fcnt = autil.tar(source, self.archiving_mode)
                if tarpath is None:
                    self.log.trace("Files count %d is lower than %d limit, "
                                   "skipping archiving",
                                   fcnt, autil.FILES_LIMIT)
                else:
                    self.log.trace("Archiving mode, tarpath: %s, file count: "
                                   "%s", tarpath, fcnt)
                    # get archive name
                    tarname = os.path.basename(tarpath)
                    self.log.trace("Archiving mode tarname: %s", tarname)
                    # archive path at the remote
                    desttarpath = os.path.join(destination, tarname)
                    self.log.trace("Archiving mode desttarpath: %s",
                                   desttarpath)
                    # transfer archive to the target
                    self.log.trace("Archiving mode: transferring")
                    self._transfer_file(tarpath, desttarpath)
                    # extract archive on the target
                    self.log.trace("Archiving mode: extracting")
                    self.extract_archive(desttarpath, self.archiving_mode)
                    # remove remote archive
                    self.log.trace("Archiving mode: removing remote archive")
                    self.rmfile(desttarpath)
                    # remove local archive
                    self.log.trace("Archiving mode: removing local archive")
                    os.remove(tarpath)
                    used_archiving = True
            if not used_archiving:
                self._transfer_dir(source, destination, umask=umask)
        elif jobs:
            raise cdist.Error("Source {} is not a directory".format(source))
        else:
            self._transfer_file(source, destination, umask=umask)

    def _transfer_dir(self, source, destination, umask=None):
        for path in glob.glob1(source, "*"):
            src_path = os.path.join(source, path)
            dst_path = os.path.join(destination, path)
            if os.path.isdir(src_path):
                self.mkdir(dst_path, umask=umask)
                self._transfer_dir(src_path, dst_path, umask=umask)
            else:
                self._transfer_file(src_path, dst_path, umask=umask)

    def run_script(self, script, env=None, return_output=False, stdout=None,
                   stderr=None):
        """Run the given script with the given environment on the target.
        Return the output as a string.
        """

        command = [
            "exec",
            self.settings.remote_shell,
            "-e",
            script
        ]

        return self.run(command, env=env, return_output=return_output,
                        stdout=stdout, stderr=stderr)

    def run(self, command, env=None, return_output=False,
            stdin=None, stdout=None, stderr=None):
        """Run the given command with the given environment on the target.
        Return the output as a string.

        If command is a list, each item of the list will be quoted if needed.
        If you need some part not to be quoted (e.g. the component is a glob),
        pass command as a str instead.
        """
        # prefix given command with remote_exec
        cmd = self._exec + [self.target_host[0]]

        if isinstance(command, (list, tuple)):
            command = shquot.join(command)

        # environment variables can't be passed to the target,
        # so prepend command with variable declarations

        # cdist command prepended with variable assignments expects
        # POSIX shell (bourne, bash) at the remote as user default shell.
        # If remote user shell isn't POSIX shell, but for e.g. csh/tcsh
        # then these var assignments are not var assignments for this
        # remote shell, it tries to execute it as a command and fails.
        # So really do this by default:
        # /bin/sh -c 'export <var assignments>; command'
        # so that constructed remote command isn't dependent on remote
        # shell. Do this only if env is not None. env breaks this.
        # Explicitly use /bin/sh, because var assignments assume POSIX
        # shell already.
        # This leaves the posibility to write script that needs to be run
        # remotely in e.g. csh and setting up CDIST_REMOTE_SHELL to e.g.
        # /bin/csh will execute this script in the right way.
        if env:
            remote_env = "export %s; " % (" ".join(
                "%s=%s" % (
                    name, shquot.quote(value) if value else "")
                for (name, value) in env.items()))
            cmd.append("/bin/sh -c " + shquot.quote(remote_env + command))
        else:
            cmd.append(command)
        return self._run_command(cmd, env=env, return_output=return_output,
                                 stdin=stdin, stdout=stdout, stderr=stderr)

    def _run_command(self, command, env=None, return_output=False,
                     stdin=None, stdout=None, stderr=None):
        """Run the given command with the given environment.
        Return the output as a string.
        """
        assert isinstance(command, (list, tuple)), (
                "list or tuple argument expected, got: {}".format(command))

        close_stdout_afterwards = False
        close_stderr_afterwards = False

        if not return_output and stdout is None:
            stdout = util.get_std_fd(self.stdout_base_path, 'remote')
            close_stdout_afterwards = True
        if stderr is None:
            stderr = util.get_std_fd(self.stderr_base_path, 'remote')
            close_stderr_afterwards = True

        # export target_host, target_hostname, target_fqdn
        # for use in __remote_{exec,copy} scripts
        os_environ = os.environ.copy()
        os_environ['__target_host'] = self.target_host[0]
        os_environ['__target_hostname'] = self.target_host[1]
        os_environ['__target_fqdn'] = self.target_host[2]

        self.log.trace("Remote run: %s", shquot.args_to_str(command))
        try:
            if return_output:
                output = subprocess.check_output(
                     command, env=os_environ,
                     stderr=stderr, stdin=stdin).decode()
            else:
                subprocess.check_call(command, env=os_environ, stdin=stdin,
                                      stdout=stdout, stderr=stderr)
                output = None

            util.log_std_fd(self.log, command, stderr, 'Remote stderr')
            util.log_std_fd(self.log, command, stdout, 'Remote stdout')

            return output
        except (OSError, subprocess.CalledProcessError) as error:
            emsg = ""
            if not isinstance(command, (str, bytes)):
                emsg += shquot.join(command)
            else:
                emsg += command
            if error.args:
                emsg += ": " + str(error.args[1])
            raise cdist.Error(emsg)
        except UnicodeDecodeError:
            raise DecodeError(command)
        finally:
            if close_stdout_afterwards:
                stdout.close()
            if close_stderr_afterwards:
                if isinstance(stderr, int):
                    os.close(stderr)
                else:
                    stderr.close()
