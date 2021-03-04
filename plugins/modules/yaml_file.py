#!/usr/bin/python

# Copyright: (c) 2021, Luke Stigdon <contact@lukestigdon.com>
from __future__ import (absolute_import, division, print_function)
from ansible.module_utils.basic import AnsibleModule
from ruamel.yaml import YAML
from tempfile import NamedTemporaryFile
from io import StringIO
import traceback
import os

from ansible.module_utils.common.parameters import PASS_BOOLS
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
  - ansible.builtin.file

options:
  dest:
    description:
      - Path to the YAML file.
    type: path
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
    default: yes

requirements:
  - ruamel.yaml
'''

EXAMPLES = r'''
## TODO
'''

RETURN = r'''
## TODO
'''


try:
    # PY3
    from collections.abc import Mapping
except ImportError:
    # PY2
    from collections import Mapping

yaml = YAML()
yaml.default_flow_style = False


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
        before_header='{} (content)'.format(dest),
        after_header='{} (content)'.format(dest)
    )

    if not os.path.exists(dest):
        if not create:
            module.fail_json(
                rc=257, msg='Path {} does not exist!'.format(dest))

        # ensure parent directories exist if we're creating the file
        destdir = os.path.dirname(dest)
        if not os.path.exists(destdir):
            os.makedirs(destdir)
    else:
        with open(dest) as f:
            data = f.read()

    if module._diff:
        # if the file was empty ensure it has atleast a newline
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
            module.fail_json(msg='Could not move tmp file {} to destination {}'.format(
                tmpfile, dest), traceback=traceback.format_exc())

    return changed, backup_file, diff, msg


def main():

    # define available arguments/parameters a user can pass to the module
    module_args = dict(
        dest=dict(type='path', required=True),
        key=dict(type='str', required=True),
        value=dict(type='raw', required=False),
        state=dict(type='str',  required=True, choices=[
                   'present', 'absent'], default='present'),
        backup=dict(type='bool', required=False, default=False),
        create=dict(type='bool', required=False, default=True),
    )

    # instantiate ansible module
    module = AnsibleModule(
        argument_spec=module_args,
        add_file_common_args=True,
        supports_check_mode=False  # TODO support check mode
    )

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
