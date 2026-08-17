# Builds the firmware's SDK-independent parts for the host, so the Python test
# suite can check both sides of the protocol against each other.
#
#   make -C tools/ctest

CC      ?= cc
CFLAGS  ?= -std=c11 -Wall -Wextra -Werror -O1 -g
PICO    := ../../firmware/pico/src
PLANE   := ../../firmware/plane/src
BUILD   := build

BINARIES := $(BUILD)/frame_decoder $(BUILD)/rc_decoder $(BUILD)/ppm_dump \
            $(BUILD)/relay_sim $(BUILD)/effect_dump $(BUILD)/bus_decoder

all: $(BINARIES)

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/frame_decoder: frame_decoder.c $(PICO)/link.c $(PICO)/crc16.c | $(BUILD)
	$(CC) $(CFLAGS) -I$(PICO) -o $@ $^

$(BUILD)/rc_decoder: rc_decoder.c | $(BUILD)
	$(CC) $(CFLAGS) -I$(PLANE) -o $@ $^

$(BUILD)/ppm_dump: ppm_dump.c | $(BUILD)
	$(CC) $(CFLAGS) -I$(PICO) -o $@ $^

$(BUILD)/relay_sim: relay_sim.c | $(BUILD)
	$(CC) $(CFLAGS) -I$(PLANE) -o $@ $^

$(BUILD)/effect_dump: effect_dump.c $(PLANE)/effects.c | $(BUILD)
	$(CC) $(CFLAGS) -I$(PLANE) -o $@ $^ -lm

$(BUILD)/bus_decoder: bus_decoder.c $(PLANE)/bus.c | $(BUILD)
	$(CC) $(CFLAGS) -I$(PLANE) -o $@ $^

clean:
	rm -rf $(BUILD)

.PHONY: all clean
