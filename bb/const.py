#!/usr/bin/env python3

FMT = "!HH"
LEN = 4
NULL = "0"  # for json

instructions_list = [
    "ping",
    "online",
    "enter",
    "move",
]

PING = 0
INST_LEN = len(instructions_list)
ONLINE = PING + instructions_list.index("online")

ATTR = 1001  # head id of all attributes

# everyone could checkout my attributes(in the public_attrs)
public_attrs = {
    "bag",
    "level",
}
