SDK_HOME ?= $(shell cat $(HOME)/.Garmin/ConnectIQ/current-sdk.cfg 2>/dev/null)
SDK_BIN := $(SDK_HOME)/bin
KEY ?= $(HOME)/.config/garmin/developer_key.der
DEVICE ?= instinct3solar45mm
MONKEYC := $(SDK_BIN)/monkeyc -f monkey.jungle -d $(DEVICE) -y $(KEY)

.PHONY: build debug test sim demo install clean

build:
	mkdir -p bin && $(MONKEYC) -r -o bin/TreadmillField.prg

debug:
	mkdir -p bin && $(MONKEYC) -o bin/TreadmillField-debug.prg

test:
	mkdir -p bin && $(MONKEYC) -t -o bin/test.prg
	$(SDK_BIN)/monkeydo bin/test.prg $(DEVICE) -t

sim:
	$(SDK_BIN)/connectiq &

demo: debug
	$(SDK_BIN)/monkeydo bin/TreadmillField-debug.prg $(DEVICE)

install: build
	-pkill -x gvfsd-mtp
	sleep 1
	/usr/bin/python3 tools/mtp_send.py bin/TreadmillField.prg Garmin/Apps

clean:
	rm -rf bin
