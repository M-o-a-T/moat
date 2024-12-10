==========
Data model
==========

DistInv models these data types:

host
====

A host always has a short name and a domain name.

It may have a default IP address and any number of ports.

Hosts' IP addresses are described by the network name, plus the host's
position in the network.

port
====

Ports are part of hosts.

A port always has a name. It may have a description, address, VLAN, and MAC.

network
=======

A network always has a name and a network address.

It may have an associated VLAN, a DHCP range, a domain template for DHCP, and a master network.

A non-slaved network can auto-allocate addresses.

vlan
====

A VLAN has a name and a number.


