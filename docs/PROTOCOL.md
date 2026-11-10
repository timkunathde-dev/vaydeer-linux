# Vaydeer 9-key Smart Keypad – USB protocol

*Deutsche Kurzfassung am Ende.*

## Device

```
lsusb:  ID 0483:5752 STMicroelectronics 9-key Smart Keypad
```

The keypad enumerates as a composite HID device with several interfaces. Linux creates
these input devices for it:

| Input device | Sends events? |
|---|---|
| `Vaydeer 9-key Smart Keypad` (keyboard) | no |
| `Vaydeer 9-key Smart Keypad Mouse` | no |
| `Vaydeer 9-key Smart Keypad Consumer Control` | no |
| `Vaydeer 9-key Smart Keypad System Control` | no |

In the tested factory state, none of them emit events when a key is pressed. Instead, one of
the four `hidraw` nodes delivers vendor-specific reports.

## Key reports

Every key press and release produces one report on the vendor `hidraw` interface:

```
byte:  0    1    2    3    4    5    6 … 15
       FB   03   xx   KK   SS   CC   00 …
```

| Byte | Meaning |
|---|---|
| 0 | `0xFB` – report marker |
| 1 | `0x03` – key event |
| 2 | varies (`0x01` or `0x02` observed), not needed |
| 3 | key index `0x00`–`0x08` (top left → bottom right) |
| 4 | `0x00` = pressed, `0x02` = released |
| 5 | checksum: XOR of bytes 0–4 |

Example (key 1 pressed and released):

```
fb 03 02 00 00 fa
fb 03 02 00 02 f8
```

Checksum check: `0xFB ^ 0x03 ^ 0x02 ^ 0x00 ^ 0x00 = 0xFA` ✓

## Capturing reports yourself

```bash
# list hidraw nodes of the keypad
for h in /sys/class/hidraw/hidraw*; do
  echo "$(basename $h): $(grep HID_NAME $h/device/uevent)"
done

# dump one node while pressing keys (try each Vaydeer node)
sudo cat /dev/hidrawX | xxd
```

If you have another Vaydeer model, please share this output in an issue.

## Open questions

- Configuring the device itself (key mapping stored on the device, LEDs, firmware) is not
  implemented. Everything happens on the computer.
- Meaning of byte 2.

---

## Kurzfassung (Deutsch)

Das Pad meldet Tastendrücke nicht als normale Tastatur, sondern über eine herstellereigene
`hidraw`-Schnittstelle. Jeder Druck und jedes Loslassen erzeugt einen Report
`FB 03 xx KK SS CC`: `KK` ist die Taste (0–8, von oben links nach unten rechts), `SS` ist
`00` für gedrückt und `02` für losgelassen, `CC` ist die XOR-Prüfsumme der Bytes 0–4.
Eigene Daten erfasst du mit den Befehlen oben; bei anderen Vaydeer-Modellen freuen wir uns
über die Ausgabe in einem Issue.
