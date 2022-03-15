'''This is a basic tool used to easily deploy VMs and ResourceGroups in Azure.
It uses the Azure SDK for Python.
Created by: Greg Diaz.
'''
import argparse
import re
import sys
import textwrap

from getpass import getpass

from azure.core.exceptions import ResourceNotFoundError, HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient



credential = DefaultAzureCredential()
subscription_client = SubscriptionClient(credential)

subscription = next(subscription_client.subscriptions.list())
subscription_id = subscription.subscription_id

resource_client = ResourceManagementClient(credential, subscription_id)
network_client = NetworkManagementClient(credential, subscription_id)
compute_client = ComputeManagementClient(credential, subscription_id)

DEFAULT_SUBNET = 'default'

parser = argparse.ArgumentParser(
description =textwrap.dedent('''
        ===================================
                     Pyzure
        ===================================
        This is a python azure-sdk tool used to manage virutal machines!'''),
        formatter_class=lambda prog: argparse.RawDescriptionHelpFormatter(prog,
            max_help_position=55),
        epilog=textwrap.dedent("""
        ---------------------------------------------------------------
                                Examples:
        ---------------------------------------------------------------
        # Provisions default VM
        pyzure.py -g MyResourceGroup -n MyVm

        # Specifies username and password
        pyzure.py -g MyResourceGroup -n MyVM --username azureusername --password 'v8$748s~AV9M'

        # Provisions a B12ms SKU sized VM
        pyzure.py -g MyResourceGroup -n MyVM --size Standard_B12ms

        # Specifies region and username
        pyzure.py -g MyResourceGroup -n MyVM --region westus2 --username azureuser
        """))
argument = parser.add_argument
argument('-g', '--resourcegroup', required=True, help='name of Resource Group')
argument('-n', '--name', required=True, help='name of VM')
argument('-r', '--region', default='eastus',
        help='location to deploy the resources in. Default is East US')
argument('-s', '--size', default='Standard_D4s_v3',
        help='size of VM you wish to deploy. Default is Standard_D4s_v3')
argument('-u', '--username', default='azureadmin',
        help='admin username of the VM, used for RDP/SSH. Default is azureadmin')
argument('-p', '--password', help='password for the admin username of the VM')

args = parser.parse_args()
vm_name = args.name
default_vnet = f'{vm_name}-vnet'
default_ip = f'{vm_name}-ip'
default_nic = f'{vm_name}-nic'

class ManageVm:
    '''This class creates the resources.
    and prints the results.
    '''
    def __init__(self, _):
        '''Constructor'''
        self.arguments = _

    def create_vm(self):
        '''This method creates the network dependancies and virtual machine'''
        vnet = network_client.virtual_networks.begin_create_or_update(self.arguments.resourcegroup,
        default_vnet,
            {
                "location" : self.arguments.region,
                "address_space" : {
                        "address_prefixes": ["10.0.0.0/16"]
                }
            }
        )
        vnet_result = vnet.result()
        output_results(vnet_result)

        subnet = network_client.subnets.begin_create_or_update(self.arguments.resourcegroup,
            default_vnet,DEFAULT_SUBNET,
            { "address_prefix" : "10.0.0.0/24" }
        )
        subnet_result = subnet.result()
        output_results(subnet_result)

        public_ip = network_client.public_ip_addresses.begin_create_or_update(
            self.arguments.resourcegroup, default_ip,
            {
                "location" : self.arguments.region,
                "sku" : { "name" : "Basic" },
                "public_ip_allocation_method" : "Static",
                "public_ip_address_version" : "IPv4"

            }
        )
        public_ip_result = public_ip.result()
        output_results(public_ip_result)

        nic = network_client.network_interfaces.begin_create_or_update(self.arguments.resourcegroup,
            default_nic,
            {
                "location" : self.arguments.region,
                "ip_configurations" : [ {
                    "name" : default_ip,
                    "subnet" : { "id" : subnet_result.id },
                    "public_ip_address" : { "id" : public_ip_result.id }
                }]
            }
        )
        nic_result = nic.result()
        output_results(nic_result)

        virtual_machine = compute_client.virtual_machines.begin_create_or_update(
            self.arguments.resourcegroup, self.arguments.name,
            {
            "location" : self.arguments.region,
            "storage_profile" : {
                "image_reference" : {
                    "publisher" : "canonical",
                    "offer" : "0001-com-ubuntu-server-focal",
                    "sku" : "20_04-lts-gen2",
                    "version" : "latest"
                }
            },
            "hardware_profile" : {
                "vm_size" : self.arguments.size
            },
            "os_profile" : {
                "computer_name" : self.arguments.name,
                "admin_username" : self.arguments.username,
                "admin_password" : self.arguments.password
            },
            "network_profile" : {
                "network_interfaces" : [
                    {
                    "id" : nic_result.id,
                    }
                ]}
            }
        )
        vm_result = virtual_machine.result()
        output_results(vm_result)

    def create_resource_group(self):
        '''If the resourcegroup doesn't exists in the subscription it will create a new one.'''
        resource_group = resource_client.resource_groups.create_or_update(
            self.arguments.resourcegroup,
        {
            "location" : self.arguments.region
        }
        )
        output_results(resource_group)


def output_results(group):
    """Print a results of resources."""
    print(f"\tName: {group.name}")
    print(f"\tId: {group.id}")
    if hasattr(group, 'location'):
        print(f"\tLocation: {group.location}")
    output_properties(getattr(group, 'properties', None))


def output_properties(properties):
    """Prints the properties of each resource."""
    if properties and hasattr(properties, 'provisioning_state'):
        print("\tProperties:")
        print(f"\t\tProvisioning State: {properties.provisioning_state}")
    print("\n\n")


def search_for_nic(nic_element):
    '''This function verifies if the subnet is in use for exception handling.
    HttpResponseError has an error SubnetAlreadyInUse, if the NIC exists and
    is floating, when trying to create a new one it will fail.
    '''
    nic_list = network_client.network_interfaces.list(args.resourcegroup)
    for _, item in enumerate(nic_list):
        if item.name != nic_element:
            return False
    return True


def search_for_vm(vm_element):
    '''This function is used to verify if VM already exists in ResourceGroup'''
    vm_list = compute_client.virtual_machines.list(args.resourcegroup)
    for _, item in enumerate(vm_list):
        if item.name == vm_element:
            return True
    return False


def validate_pass(password):
    '''This function validates the password to meet the requirements'''
    pwd_regex = r'^(?=\S{12,123}$)(?=.*?\d)(?=.*?[a-z])(?=.*?[A-Z])(?=.*?[^A-Za-z\s0-9])'
    compiled_regex = re.compile(pwd_regex)

    if re.search(compiled_regex, password):
        return True
    return False


def prompt_pass():
    '''If password is not entered as an argument, it will prompt user for password.'''
    args.password = getpass(textwrap.dedent('''
    The supplied password must be between 12-123 characters long and must satisfy all of password complexity requirements from the following:
        1) Contains an uppercase character
        2) Contains a lowercase character
        3) Contains a numeric digit
        4) Contains a special character
        5) Control characters are not allowed
    Enter admin password: '''))

    if args.password != getpass("Confirm password: "):
        print("Password does not match. Please try again: ")
        sys.exit()


def main():
    '''This function initalizes the class,
    validates the password in the argument field,
    prompts password if not entered as an argument,
    and does some exception handling.
    '''
    manage_vm = ManageVm(args)

    if args.password is None:
        prompt_pass()

    validate_pass(args.password)
    if validate_pass(args.password) is not True:
        print("Invalid password: Does not meet requirements.")
        sys.exit()

    try:
        manage_vm.create_vm()
    except ResourceNotFoundError:
        manage_vm.create_resource_group()
        manage_vm.create_vm()
    except HttpResponseError:
        if search_for_vm(args.name):
            print(f"VM named \'{args.name}\' already exists in \'{args.resourcegroup}\'.")
        elif search_for_nic(default_nic):
            print(f"Nic named \'{default_nic}\' already exists in \'{args.resourcegroup}\'.")


if __name__ == "__main__":
    main()
