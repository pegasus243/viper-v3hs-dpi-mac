"""Affiche tous les reglages lus dans la souris. Lecture seule."""
import razer_hid as hid

state = hid.read_all()
print(f"Taux de scrutation : {state['poll']} Hz" if state["poll"] else "Taux de scrutation : illisible")
if state["dpi"]:
    print(f"DPI courant        : X={state['dpi']['x']}  Y={state['dpi']['y']}")
if state["stages"]:
    stages = state["stages"]
    print(f"Paliers DPI        : {stages['count']} paliers, actif = {stages['active']}")
    for stage in stages["stages"]:
        mark = "   <= ACTIF" if stage["number"] == stages["active"] else ""
        value = stage["x"] if stage["x"] == stage["y"] else f"{stage['x']}/{stage['y']}"
        print(f"   palier {stage['number']} : {value}{mark}")
    print(f"\nRAW paliers (38o)  : {stages['raw']}")
if state["idle"]:
    print(f"\nMise en veille     : {state['idle']} s")
if state["battery"]:
    charge = " (en charge)" if state["charging"] else ""
    print(f"Batterie           : {state['battery']['percent']} %{charge}")
if state["threshold"]:
    print(f"Alerte batterie    : {state['threshold']['percent']} %")
for name, message in state["errors"].items():
    print(f"  !! {name} : {message}")
