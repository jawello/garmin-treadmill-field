"""Status packets captured from the user's R1 Pro on 2026-09-25."""

STOPPED = bytes.fromhex("f8a200000100000000000000000000000000a3fd")
WALKING = bytes.fromhex("f8a2012d01" "000082" "000010" "0000e6" "00000000" "49fd")  # 4.5 km/h, 130 s, 160 m, 230 steps
BUTTON = bytes.fromhex("f8a201320100002a000004000045000002004bfd")  # remote button byte set
COUNTDOWN = bytes.fromhex("f8a2090001000000000000000000000003" "00affd")
STOPPING = bytes.fromhex("f8a20307010000" "0e" "000000" "00000e" "00000000" "c9fd")
