# -*- coding: utf-8 -*-
#
# 2016-2017 Darko Poljak (darko.poljak at gmail.com)
# 2025 Dennis Camera (dennis.camera at riiengineering.ch)
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
#

import itertools
import os
import subprocess

import cdist

from collections import OrderedDict
from tempfile import TemporaryFile

from cdist.util import shquot


# IMPORTANT:
# with the code below in python 3.5 when command is executed and error
# occurs then stderr is not captured.
# As it seems from documentation, it is only captured when using
# subprocess.run method with stderr=subprocess.PIPE and is captured
# into CompletedProcess resulting object or into CalledProcessError
# in case of error (only if specified capturing).
#
# If using PIPE then the run is slow. run method uses communicate method
# and internally it uses buffering.
#
# For now we will use capturing only stdout. stderr is written directly to
# stderr from child process.
#
# STDERR_UNSUPPORTED = '<Not supported in this python version>'
#
#
# def call_get_output(command, env=None):
#     """Run the given command with the given environment.
#     Return the tuple of stdout and stderr output as a byte strings.
#     """
#
#     assert isinstance(command, (list, tuple)), (
#             "list or tuple argument expected, got: {}".format(command))
#
#     if sys.version_info >= (3, 5):
#         return call_get_out_err(command, env)
#     else:
#         return (call_get_stdout(command, env), STDERR_UNSUPPORTED)
#
#
# def handle_called_process_error(err, command):
#     if sys.version_info >= (3, 5):
#         errout = err.stderr
#     else:
#         errout = STDERR_UNSUPPORTED
#     raise cdist.Error("Command failed: " + " ".join(command) +
#              " with returncode: {} and stdout: {}, stderr: {}".format(
#                           err.returncode, err.output, errout))
#
#
# def call_get_stdout(command, env=None):
#     """Run the given command with the given environment.
#     Return the stdout output as a byte string, stderr is ignored.
#     """
#     assert isinstance(command, (list, tuple)), (
#         "list or tuple argument expected, got: {}".format(command))
#
#     with TemporaryFile() as fout:
#         subprocess.check_call(command, env=env, stdout=fout)
#         fout.seek(0)
#         output = fout.read()
#
#     return output
#
#
# def call_get_out_err(command, env=None):
#     """Run the given command with the given environment.
#     Return the tuple of stdout and stderr output as a byte strings.
#     """
#     assert isinstance(command, (list, tuple)), (
#         "list or tuple argument expected, got: {}".format(command))
#
#     with TemporaryFile() as fout, TemporaryFile() as ferr:
#         subprocess.check_call(command, env=env,
#                               stdout=fout, stderr=ferr)
#         fout.seek(0)
#         ferr.seek(0)
#         output = (fout.read(), ferr.read())
#
#     return output

#
# The code below with bufsize=0 does not work either, communicate
# internally uses buffering. It works in case of error, but if everything
# is ok and there is no output in stderr then execution is very very slow.
#
# def _call_get_out_err(command, env=None):
#     """Run the given command with the given environment.
#     Return the tuple of stdout and stderr output as a byte strings.
#     """
#     assert isinstance(command, (list, tuple)), (
#         "list or tuple argument expected, got: {}".format(command))
#
#     result = subprocess.run(command, env=env, bufsize=0,
#             stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
#
#     return (result.stdout, result.stderr)


# Currently not used.
def call_get_output(command, env=None, stderr=None):
    """Run the given command with the given environment.
    Return the tuple of stdout and stderr output as a byte strings.
    """

    assert isinstance(command, (list, tuple)), (
            "list or tuple argument expected, got: {}".format(command))
    return (_call_get_stdout(command, env, stderr), None)


# Currently not used.
def handle_called_process_error(err, command):
    # Currently, stderr is not captured.
    # errout = None
    # raise cdist.Error("Command failed: " + " ".join(command) +
    #                   (" with returncode: {}\n"
    #                    "stdout: {}\n"
    #                    "stderr: {}").format(
    #                       err.returncode, err.output, errout))
    output = err.output if err.output else ""
    raise cdist.Error(("Command failed: '{}'\n"
                      "return code: {}\n"
                       "---- BEGIN stdout ----\n"
                       "{}" + ("\n" if output else "") +
                       "---- END stdout ----").format(
                          " ".join(command), err.returncode, output))


# Currently not used.
def _call_get_stdout(command, env=None, stderr=None):
    """Run the given command with the given environment.
    Return the stdout output as a byte string, stderr is ignored.
    """
    assert isinstance(command, (list, tuple)), (
        "list or tuple argument expected, got: {}".format(command))

    with TemporaryFile() as fout:
        subprocess.check_call(command, env=env, stdout=fout, stderr=stderr)
        fout.seek(0)
        output = fout.read()

    return output


def get_std_fd(base_path, name):
    path = os.path.join(base_path, name)
    return open(path, 'ba+')


# subprocess.DEVNULL is added in 3.3.
if hasattr(subprocess, 'DEVNULL'):
    def log_std_fd(log, command, stdfd, prefix):
        if stdfd is not None and stdfd != subprocess.DEVNULL:
            stdfd.seek(0, 0)
            log.trace("Command: %s; %s: %s",
                      shquot.args_to_str(command),
                      prefix, stdfd.read().decode())
else:
    def log_std_fd(log, command, stdfd, prefix):
        if stdfd is not None and not isinstance(stdfd, int):
            stdfd.seek(0, 0)
            log.trace("Command: %s; %s: %s",
                      shquot.args_to_str(command),
                      prefix, stdfd.read().decode())


def resolve_conf_dirs(*args):
    return list(OrderedDict.fromkeys(itertools.chain.from_iterable(args)))
