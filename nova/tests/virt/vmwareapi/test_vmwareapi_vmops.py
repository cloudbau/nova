# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock

from nova.network import model as network_model
from nova import test
from nova import utils
from nova.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vmops


class fake_session(object):
    def __init__(self, ret=None):
        self.ret = ret

    def _get_vim(self):
        return vmwareapi_fake.FakeVim()

    def _call_method(self, module, method, *args, **kwargs):
        return self.ret

    def _wait_for_task(self, task_ref):
        return


class VMwareVMOpsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(VMwareVMOpsTestCase, self).setUp()
        subnet_4 = network_model.Subnet(cidr='192.168.0.1/24',
                                        dns=[network_model.IP('192.168.0.1')],
                                        gateway=
                                            network_model.IP('192.168.0.1'),
                                        ips=[
                                            network_model.IP('192.168.0.100')],
                                        routes=None)
        subnet_6 = network_model.Subnet(cidr='dead:beef::1/64',
                                        dns=None,
                                        gateway=
                                            network_model.IP('dead:beef::1'),
                                        ips=[network_model.IP(
                                            'dead:beef::dcad:beff:feef:0')],
                                        routes=None)
        network = network_model.Network(id=0,
                                        bridge='fa0',
                                        label='fake',
                                        subnets=[subnet_4, subnet_6],
                                        vlan=None,
                                        bridge_interface=None,
                                        injected=True)
        self.network_info = network_model.NetworkInfo([
                network_model.VIF(id=None,
                                  address='DE:AD:BE:EF:00:00',
                                  network=network,
                                  type=None,
                                  devname=None,
                                  ovs_interfaceid=None,
                                  rxtx_cap=3)
                ])
        utils.reset_is_neutron()
        self._session = fake_session()

    def test_get_machine_id_str(self):
        result = vmops.VMwareVMOps._get_machine_id_str(self.network_info)
        self.assertEqual(result,
                         'DE:AD:BE:EF:00:00;192.168.0.100;255.255.255.0;'
                         '192.168.0.1;192.168.0.255;192.168.0.1#')

    def test_is_neutron_nova(self):
        self.flags(network_api_class='nova.network.api.API')
        ops = vmops.VMwareVMOps(None, None, None)
        self.assertFalse(ops._is_neutron)

    def test_is_neutron_neutron(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        ops = vmops.VMwareVMOps(None, None, None)
        self.assertTrue(ops._is_neutron)

    def test_is_neutron_quantum(self):
        self.flags(network_api_class='nova.network.quantumv2.api.API')
        ops = vmops.VMwareVMOps(None, None, None)
        self.assertTrue(ops._is_neutron)

    def test_use_linked_clone_override_nf(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, False)
        self.assertFalse(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_nt(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, True)
        self.assertTrue(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_ny(self):
        value = vmops.VMwareVMOps.decide_linked_clone(None, "yes")
        self.assertTrue(value, "No overrides present but still overridden!")

    def test_use_linked_clone_override_ft(self):
        value = vmops.VMwareVMOps.decide_linked_clone(False, True)
        self.assertFalse(value,
                        "image level metadata failed to override global")

    def test_use_linked_clone_override_nt(self):
        value = vmops.VMwareVMOps.decide_linked_clone("no", True)
        self.assertFalse(value,
                        "image level metadata failed to override global")

    def test_use_linked_clone_override_yf(self):
        value = vmops.VMwareVMOps.decide_linked_clone("yes", False)
        self.assertTrue(value,
                        "image level metadata failed to override global")

    def _test_get_datacenter_ref_and_name(self, ds_ref_exists=False):
        instance_ds_ref = mock.Mock()
        instance_ds_ref.value = "ds-1"
        _vcvmops = vmops.VMwareVCVMOps(self._session, None, None)
        if ds_ref_exists:
            ds_ref = mock.Mock()
            ds_ref.value = "ds-1"
        else:
            ds_ref = None

        def fake_call_method(module, method, *args, **kwargs):
            fake_object1 = vmwareapi_fake.FakeRetrieveResult()
            fake_object1.add_object(vmwareapi_fake.Datacenter(
                ds_ref=ds_ref))
            if not ds_ref:
                # Token is set for the fake_object1, so it will continue to
                # fetch the next object.
                setattr(fake_object1, 'token', 'token-0')
                if method == "continue_to_get_objects":
                    fake_object2 = vmwareapi_fake.FakeRetrieveResult()
                    fake_object2.add_object(vmwareapi_fake.Datacenter())
                    return fake_object2

            return fake_object1

        with mock.patch.object(self._session, '_call_method',
                               side_effect=fake_call_method) as fake_call:
            dc_info = _vcvmops.get_datacenter_ref_and_name(instance_ds_ref)

            if ds_ref:
                self.assertEqual(1, len(_vcvmops._datastore_dc_mapping))
                fake_call.assert_called_once_with(vim_util, "get_objects",
                    "Datacenter", ["name", "datastore", "vmFolder"])
                self.assertEqual("ha-datacenter", dc_info.name)
            else:
                calls = [mock.call(vim_util, "get_objects", "Datacenter",
                                   ["name", "datastore", "vmFolder"]),
                         mock.call(vim_util, "continue_to_get_objects",
                                   "token-0")]
                fake_call.assert_has_calls(calls)
                self.assertIsNone(dc_info)

    def test_get_datacenter_ref_and_name(self):
        self._test_get_datacenter_ref_and_name(ds_ref_exists=True)

    def test_get_datacenter_ref_and_name_with_no_datastore(self):
        self._test_get_datacenter_ref_and_name()
