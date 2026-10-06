"""Ecrit les paliers DPI onboard, avec sauvegarde et relecture octet par octet.

  set_stages.py --read
  set_stages.py 400 800 1600 2400 3200 [--active N]
  set_stages.py --restore stages-backup.hex
"""
import os
import sys

import razer_hid as hid

BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stages-backup.hex")


def show(stages, title):
    print(f"{title} : {stages['count']} paliers, actif = {stages['active']}")
    for stage in stages["stages"]:
        mark = "   <= ACTIF" if stage["number"] == stages["active"] else ""
        value = stage["x"] if stage["x"] == stage["y"] else f"{stage['x']}/{stage['y']}"
        print(f"   palier {stage['number']} : {value}{mark}")


def save():
    block = hid.read_stage_block()
    with open(BACKUP, "w") as handle:
        handle.write(block.hex())
    return hid.decode_stages(block)


args = sys.argv[1:]
try:
    if not args or args[0] == "--read":
        current = save()
        show(current, "config actuelle")
        print(f"\nsauvegarde ecrite dans {BACKUP} :\n{current['raw']}")
    elif args[0] == "--restore":
        path = args[1] if len(args) > 1 else BACKUP
        with open(path) as handle:
            saved = handle.read().strip()
        show(hid.restore_block(saved), "\nconfig restauree et relue")
    else:
        active = None
        if "--active" in args:
            index = args.index("--active")
            active = int(args[index + 1])
            args = args[:index] + args[index + 2:]
        values = [int(value) for value in args]
        show(save(), "config actuelle (sauvegardee)")
        result = hid.write_stages(values, active)
        if result["changed"]:
            show(result, "\nconfig ecrite et relue octet par octet")
        else:
            print("\naucune modification a ecrire")
except hid.DeviceError as error:
    raise SystemExit(f"\nerreur : {error}")
except (IndexError, ValueError) as error:
    raise SystemExit(f"\nargument invalide : {error}")
