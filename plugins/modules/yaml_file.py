#!/usr/bin/python

# Copyright: (c) 2021, Luke Stigdon <contact@lukestigdon.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: yaml_file
version_added: "1.0.0"
short_description: Manage content in a YAML file

author:
  - Luke Stigdon (@lstig)

description:
  - This module manges the presence and absence of keys in a YAML file wihtout needing to template the entire file.

extends_documentation_fragment:
  - ansible.builtin.files

options:
  dest:
    description:
      - Path to the YAML file.
    type: path
    aliases: ['path']
    required: true
  key:
    description:
      - The key to manage in a YAML file.
      - The key is created if C(state=present) and it does not exist.
    type: str
    required: true
  value:
    description:
      - The value to set for managed I(key).
      - May be omitted when removing a I(key).
    type: raw
  state:
    description:
      - If set to C(absent) the I(key) will be removed.
    type: str
    choices: [ present, absent ]
    default: present
  backup:
    description:
      - Create a backup incase the file is clobbered inadvertently.
    type: bool
    default: no
  create:
    description:
      - If set to C(no), the module will fail if the file does not already exist.
      - By default it will create the file if it is missing.
    type: bool
    aliases: ['force']
    default: yes

requirements:
  - "ruamel.yaml>=0.16"
'''

EXAMPLES = r'''
# manage a key/value in a file
- name: Set some_setting
  lstig.general.yaml_file:
    dest: /etc/foo/config.yaml
    key: some_setting
    value: 8080

- name: Remove some_setting
  lstig.general.yaml_file:
    dest: /etc/foo/config.yaml
    key: some_setting
    state: absent

# use '.' if the key part of hash e.g.
# ---
# some:
#   nested:
#     setting: 8080
- name: Set some_setting
  lstig.general.yaml_file:
    dest: /etc/foo/config.yaml
    key: some.nested.setting
    value: 8080

# backup up the file before making changes
- name: Set some_setting but backup the file
  lstig.general.yaml_file:
    dest: /etc/foo/config.yaml
    key: some_setting
    value: 8080
    backup: yes

# the module also supports managing file permissions
- name: Set some_setting and manage file perms
  lstig.general.yaml_file:
    dest: /etc/foo/config.yaml
    owner: root
    group: wheel
    mode: '0640'
    key: some_setting
    value: 8080
'''

import os
import traceback
from io import StringIO
from tempfile import NamedTemporaryFile

from ansible.module_utils.basic import AnsibleModule, missing_required_lib
from ansible.module_utils.common._collections_compat import Mapping  # waiting on ansible.module_utils.six

try:
    from ruamel.yaml import YAML

    MISSING_LIB = False
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.representer.ignore_aliases = lambda *args: True
except ImportError as e:
    MISSING_LIB_ERROR = e
    MISSING_LIB = True


def dig(dct, keys):
    '''Drill down into a dictionary with the given list of keys'''
    for key in keys:
        dct = dct[key]
    return dct


def merge(dct, other):
    '''Safely update dct with values from other without clobbering subkeys'''
    for k, v in other.items():
        if isinstance(v, Mapping):
            dct[k] = merge(dct.get(k, {}), v)
        else:
            dct[k] = v
    return dct


def run_module(module, dest, key, value, state, backup, create, *args, **kwargs):

    diff = dict(
        before='',
        after='',
        before_header='{0} (content)'.format(dest),
        after_header='{0} (content)'.format(dest)
    )

    data = ''
    if not os.path.exists(dest):
        if not create:
            module.fail_json(
                rc=257, msg='Path {0} does not exist!'.format(dest))

        # ensure parent directories exist if we're creating the file
        destdir = os.path.dirname(dest)
        if destdir and not os.path.exists(destdir):
            os.makedirs(destdir)
    else:
        with open(dest) as f:
            data = f.read()

    if module._diff:
        # if the file was empty ensure it has atleast a newline (for diff output reasons)
        diff['before'] = data if data else '\n'

    # parse the yaml
    data = yaml.load(data) or {}

    # keys can be expressed with dotted notation e.g.: this.is.a.key == {'this':{'is':{'a':'key':{}}}}
    keys = key.split('.')
    msg = 'OK'
    changed = False

    if state == 'present':
        try:
            # check current value against expected
            current = dig(data, keys)
            if value != current:
                changed = True
                msg = 'value changed'
        except KeyError:
            # key does not exist, it needs to be added!
            changed = True
            msg = 'key added'

        if changed:
            # created a dictionary to use for merging
            tmpdict = this = {}
            for i, key in enumerate(keys, 1):
                if i == len(keys):
                    this[key] = value
                else:
                    this[key] = {}
                    this = this[key]

            # merge the existing data with the new dictionary
            data = merge(data, tmpdict)

    elif state == 'absent':
        try:
            e = dig(data, keys[:-1])
            del e[keys[-1]]
            changed = True
            msg = 'key removed'
        except KeyError:
            # key does not exist, we're good to go!
            pass

    if module._diff:
        # dump yaml to string buffer
        with StringIO as buff:
            yaml.dump(data, buff)
            after = buff.getvalue()
        diff['after'] = after if after else '\n'

    backup_file = None
    if changed:
        if backup:
            backup_file = module.backup_local(dest)

        try:
            # write new data to temporary file
            with NamedTemporaryFile(mode='w+', dir=module.tmpdir, delete=False) as f:
                tmpfile = f.name
                yaml.dump(data, f)
        except IOError:
            module.fail_json(msg='Could not create temporary file',
                             traceback=traceback.format_exc())

        try:
            # replace current file with the temporary file
            module.atomic_move(tmpfile, dest)
        except IOError:
            module.fail_json(msg='Could not move tmp file {0} to destination {1}'.format(
                tmpfile, dest), traceback=traceback.format_exc())

    return changed, backup_file, diff, msg


def main():

    # define available arguments/parameters a user can pass to the module
    module_args = dict(
        dest=dict(type='path', required=True, aliases=['path']),
        key=dict(type='str', required=True),
        value=dict(type='raw', required=False),
        state=dict(type='str', required=False, choices=['present', 'absent'], default='present'),
        backup=dict(type='bool', required=False, default=False),
        create=dict(type='bool', required=False, default=True, aliases=['force']),
    )

    # instantiate ansible module
    module = AnsibleModule(
        argument_spec=module_args,
        add_file_common_args=True,
        supports_check_mode=False  # TODO support check mode
    )

    # exit if any required external module imports failed
    if MISSING_LIB:
        module.exit_json(msg=missing_required_lib(MISSING_LIB.name),
                         exception=MISSING_LIB_ERROR)

    # do the stuff
    changed, backup_file, diff, msg = run_module(module, **module.params)

    # apply file system args e.g. owner/group/mode
    if os.path.exists(module.params['dest']):
        file_args = module.load_file_common_arguments(module.params)
        changed = module.set_fs_attributes_if_different(file_args, changed)

    # gather results
    results = dict(
        changed=changed,
        diff=diff,
        path=module.params['dest'],
        msg=msg
    )

    if backup_file:
        results['backup_file'] = backup_file

    # Done!
    module.exit_json(**results)


if __name__ == '__main__':
    main()
