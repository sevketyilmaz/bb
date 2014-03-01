#!/usr/bin/env python3

import time
import collections

from bb import i
from bb.inst import handle, pre

i.register_default(lambda _: [0, 0], "xy")

MAX = 64  # max in a map
all_rooms = set(range(10))  # dummy rooms

room_ids = {}
rooms = collections.defaultdict(collections.OrderedDict)
slots = {}


@handle
@pre(list, lambda x: len(x) == 2 and all(isinstance(i, int) for i in x))
def move(i, xy):
    """x and y
    """
    id = i.i
    cmd = "move"
    rid = room_ids[id]
    room = rooms[rid]
    p = room[id]
    p[:2] = xy
    cache = []
    if id in slots[rid]:
        _ = {id: xy}
        cache.extend([k, cmd, _] for k in room if k != id)
    return cache



@handle
@pre(int, lambda i: i in all_rooms)
def enter(i, rid):
    """exit when rid is 0
    """
    id = i.i
    cmd = "enter"
    cache = []
    if id in room_ids or not rid:  # pop from this room
        rid, _rid = room_ids.pop(id), rid
        room = rooms[rid]
        room.pop(id)
        slot = slots[rid]
        if id in slot:
            slots[rid] = _slot = set(k for _, k in zip(range(MAX), room.keys()))
            _ = {id: None}
            for k in _slot - slot:  # supplement
                _[k] = room[k]
            cache.extend([k, cmd, _] for k in room)
        rid = _rid
    if rid:
        data = i["xy"][:]
        data.append(id)  # todo: append more infomations
        room = rooms[rid]
        room[id], room_ids[id], staff, slot = data, rid, {}, set()
        for _, kv in zip(range(MAX), room.items()):  # build staff
            k, v = kv
            slot.add(k)
            if k != id:
                staff[k] = v
        slots[rid] = slot  # and rebuild slot
        cache.append([i.i, cmd, staff])
        if id in slot:
            _ = {id: data}
            cache.extend([k, cmd, _] for k in room if k != id)
    return cache
