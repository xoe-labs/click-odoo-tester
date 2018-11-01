#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# This file is part of the click-odoo-tester (R) project.
# Copyright (c) 2018 XOE Corp. SAS
# Authors: David Arnold, et al.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library; if not, see <http://www.gnu.org/licenses/>.
#

import logging
import os
import subprocess
from contextlib import contextmanager

import click
import psycopg2
from click_odoo import CommandWithOdooEnv, odoo
from future.types import str

from .format import process

# from utils import manifest, gitutils

_logger = logging.getLogger(__name__)


class Git(object):
    def __init__(self, git_dir):
        self.git_dir = git_dir

    def run(self, command):
        """Execute git command in bash
        :param list command: Git cmd to execute in self.git_dir
        :return: String output of command executed.
        """
        cmd = ["git", "--git-dir=" + self.git_dir] + command
        try:
            res = subprocess.check_output(cmd)
        except subprocess.CalledProcessError:
            res = None
        if isinstance(res, str):
            res = res.strip("\n")
        return res

    def fetch_remote(self, ref):
        """ Fetches a remote ref, independent of current refspec config """
        if "/" not in ref:
            return
        original = self.run(["config", "--get", "remote.origin.fetch"])
        parts = ref.split("/", 1)
        remote = parts[0]
        ref_branch = parts[1]
        self.run(
            [
                "config",
                "remote.origin.fetch",
                "+refs/heads/{ref_branch}:refs/remotes/{remote}/{ref_branch}".format(
                    **locals()
                ),
            ]
        )
        self.run(["fetch"] + parts)
        self.run(["config", "remote.origin.fetch", original])

    def get_changed_paths(self, base_ref="HEAD"):
        """Get name of items changed in self.git_dir
        This is a wrapper method of git command:
            git diff-index --name-only --cached {base_ref}
        :param base_ref: String of branch or sha base.
            e.g. "master" or "SHA_NUMBER"
        :return: List of name of items changed
        """
        self.fetch_remote(base_ref)
        command = ["diff-index", "--name-only", "--cached", base_ref]
        res = self.run(command)
        items = res.decode("UTF-8").split("\n") if res else []
        return items

    def get_branch_name(self):
        """Get branch name
        :return: String with name of current branch name"""
        command = ["rev-parse", "--abbrev-ref", "HEAD"]
        res = self.run(command)
        return res


def _get_changed_modules_from_git(git_dir, base_ref="origin/master"):
    """ Returns odoo changed odoo modules as per git diff-index.
    :param base_ref: branch or remote/branch or sha to compare
    :return: List of unique modules changed """

    changed_paths = Git(git_dir).get_changed_paths(base_ref)
    res = []
    for path in changed_paths:
        res.append(os.path.basename(odoo.modules.module.get_module_root(path)))
    return set(res)


class CommandWithOdooEnvExtended(CommandWithOdooEnv):
    def _parse_env_args(self, ctx):
        odoo_args = super(CommandWithOdooEnvExtended, self)._parse_env_args(ctx)

        def _get(flag):
            return ctx.params.get(flag)

        # fmt: off
        # Always present params
        git_dir      = _get("git_dir")       # noqa
        include      = _get("include")       # noqa
        exclude      = _get("exclude")       # noqa
        tags         = _get("tags")          # noqa
        # fmt: on

        if tags:
            odoo_args.extend(["--test-tags", tags])
        odoo_args.extend(["--test-enable"])
        odoo_args.extend(["--log-db"])
        odoo_args.extend(["--log-db-level", "warning"])

        changed = _get_changed_modules_from_git(git_dir) if git_dir else set()
        modules = (changed | set(include)) - set(exclude)

        if not modules:
            click.echo("No module to test. Exiting...")
            click.get_current_context().exit()
        odoo_args.extend(["-i", ",".join(modules)])
        odoo_args.extend(["-u", ",".join(modules)])
        return odoo_args


@contextmanager
def OdooTestExecution(self):
    yield odoo.service.server.start(preload=self.database, stop=True)
    ctx = click.get_current_context()

    with psycopg2.connect(dbname=self.database) as conn:
        with conn.cursor() as cr:
            cr.execute("SELECT * FROM ir_logging")
            logs = cr.fetchall()
    conn.close()
    success = process(logs)
    if not success:
        ctx.fail("Tests failed")


@click.command(
    cls=CommandWithOdooEnvExtended,
    env_options={"with_rollback": False, "environment_manager": OdooTestExecution},
    default_overrides={"log_level": "warn"},
)
@click.option(
    "--git-dir", default=False, help="Autodetect changed modules (through git)."
)
@click.option("--include", "-i", multiple=True, help="Force test run on those modules.")
@click.option(
    "--exclude",
    "-e",
    multiple=True,
    help="Force excluding those modules from tests. Even if "
    "a change has been detected.",
)
@click.option("--tags", "-t", multiple=True, help="Filter on those test tags.")
def main(env, auto, include, exclude, tags):
    """ Run Odoo tests through modern pytest instead of unittest.
    """


if __name__ == "__main__":  # pragma: no cover
    main()
