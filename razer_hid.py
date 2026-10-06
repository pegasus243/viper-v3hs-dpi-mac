"""Acces HID a la Razer Viper V3 HyperSpeed : protocole et encodage des reglages.

Les reglages voyagent dans des Feature Reports de 91 octets echanges avec le
recepteur. Un handle neuf est ouvert pour chaque transaction : garder le handle
ouvert fait repondre le recepteur en statut 0x04 (timeout) alors que le pointeur
continue de fonctionner.

Protocole documente par le projet open-Viper3HS (https://github.com/hitsmaxft/open-Viper3HS)
et par OpenRazer. Ce fichier est une implementation independante.

Toute ecriture est relue et comparee avant d'etre declaree reussie.
"""
import os
import subprocess
import threading
import time

import hid

VID = 0x1532
PID = 0x00B8
REPORT_LEN = 91
TX = 0x1F
POLL_CODES = {1: 1000, 2: 500, 8: 125}
POLL_ENCODE = {1000: 1, 500: 2, 125: 8}
GMS = "com.razer.gms"
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.razer.gms.plist")

_lock = threading.Lock()


class DeviceError(RuntimeError):
    """Erreur exploitable cote interface."""


# --- service Synapse -------------------------------------------------------
# com.razer.gms parle au recepteur en parallele et fait echouer chaque
# transaction de configuration avec le statut 0x04 (timeout).

def gms_loaded():
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    return GMS in out


def gms_stop():
    if not gms_loaded():
        return False
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{GMS}"],
                   capture_output=True, text=True)
    return True


def gms_start():
    # On tente toujours : launchctl list garde le service en liste une seconde
    # apres un bootout, donc se fier a gms_loaded() ici raterait la relance.
    # Un bootstrap sur un service deja charge echoue sans effet de bord.
    if not os.path.exists(PLIST):
        return False
    done = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", PLIST],
                          capture_output=True, text=True)
    return done.returncode == 0


# --- transactions ----------------------------------------------------------

def _report(cls, cmd, data):
    r = bytearray(91)
    r[2] = TX
    r[6] = len(data)
    r[7] = cls
    r[8] = cmd
    r[9:9 + len(data)] = data
    x = 0
    for b in r[3:89]:
        x ^= b
    r[89] = x
    return bytes(r)


STATUS = {0: "non traite", 1: "occupe", 2: "succes", 3: "refuse par la souris",
          4: "timeout (Synapse occupe le canal ?)", 5: "non supporte par ce firmware"}


def _candidates():
    """Collections HID du recepteur, interface 0 en tete : c'est la seule que
    macOS laisse ouvrir (les interfaces 1 et 2 contiennent un clavier)."""
    items = list(hid.enumerate(VID, PID))
    return sorted(items, key=lambda item: (item.get("interface_number") != 0,
                                           item.get("interface_number", 99)))


def _exchange_once(report):
    """Ouvre, echange, ferme. Renvoie le rapport de reponse normalise (91 octets)."""
    errors = []
    for item in _candidates():
        device = hid.device()
        try:
            device.open_path(item["path"])
        except OSError as error:
            errors.append(str(error))
            continue
        try:
            written = device.send_feature_report(report)
            if written not in (90, 91):
                raise DeviceError(f"ecriture du Feature Report de longueur inattendue : {written}")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                time.sleep(0.05)
                raw = bytes(device.get_feature_report(0, REPORT_LEN))
                if len(raw) not in (90, 91):
                    continue
                answer = b"\0" + raw if len(raw) == 90 else raw
                if (answer[2] == report[2] and answer[7:9] == report[7:9]
                        and answer[1] != 1):          # 1 = occupe, on attend
                    return answer
            raise DeviceError("la souris n'a pas repondu dans les 3 secondes")
        finally:
            device.close()
    raise DeviceError("aucune interface du recepteur 1532:00B8 n'a pu etre ouverte"
                      + (f" : {errors[-1]}" if errors else " (recepteur debranche ?)"))


def transact(cls, cmd, data=b"\0"):
    """Une transaction = un handle neuf. Renvoie la charge utile (82 octets)."""
    with _lock:
        try:
            resp = _exchange_once(_report(cls, cmd, bytes(data)))
        except DeviceError:
            # Synapse a peut-etre ete relance entre temps : on retente une fois.
            if not gms_stop():
                raise
            resp = _exchange_once(_report(cls, cmd, bytes(data)))
    if resp[1] != 2:
        raise DeviceError(f"commande {cls:02x}/{cmd:02x} : statut 0x{resp[1]:02x} "
                          f"({STATUS.get(resp[1], 'inconnu')})")
    return resp[9:]


# --- lectures --------------------------------------------------------------

def read_poll():
    return POLL_CODES.get(transact(0, 0x85, b"\0")[0])


def read_dpi():
    p = transact(4, 0x85, b"\0")
    return {"x": (p[1] << 8) | p[2], "y": (p[3] << 8) | p[4]}


def read_stage_block():
    block = bytearray(transact(4, 0x86, b"\x01" + bytes(0x25))[:38])
    if block[2] > 5:
        raise DeviceError(f"nombre de paliers inattendu : {block[2]}")
    return block


def decode_stages(block):
    stages = []
    for index in range(block[2]):
        o = 3 + index * 7
        stages.append({"number": block[o],
                       "x": (block[o + 1] << 8) | block[o + 2],
                       "y": (block[o + 3] << 8) | block[o + 4]})
    return {"active": block[1], "count": block[2], "stages": stages,
            "raw": block.hex()}


def read_idle():
    p = transact(7, 0x83, b"\0\0")
    return (p[0] << 8) | p[1]


def read_battery():
    raw = transact(7, 0x80, b"\0\0")[1]
    return {"percent": round(raw * 100 / 255), "raw": raw}


def read_charging():
    return bool(transact(7, 0x84, b"\0\0")[1])


def read_threshold():
    raw = transact(7, 0x81, b"\0")[0]
    return {"percent": round(raw * 100 / 255), "raw": raw}


def read_all():
    """Lit tout ; un reglage en echec n'empeche pas les autres de remonter."""
    state, errors = {}, {}
    for name, reader in (("poll", read_poll), ("dpi", read_dpi),
                         ("stages", lambda: decode_stages(read_stage_block())),
                         ("idle", read_idle), ("battery", read_battery),
                         ("charging", read_charging), ("threshold", read_threshold)):
        try:
            state[name] = reader()
        except Exception as error:
            state[name] = None
            errors[name] = str(error)
    state["errors"] = errors
    return state


# --- ecritures (toutes relues) --------------------------------------------

def write_stages(values, active=None):
    block = read_stage_block()
    if len(values) != block[2]:
        raise DeviceError(f"la souris a {block[2]} paliers, {len(values)} valeurs fournies ; "
                          "changer le nombre de paliers n'est pas supporte")
    for v in values:
        if not isinstance(v, int) or not 100 <= v <= 30000:
            raise DeviceError(f"DPI hors bornes : {v} (100 a 30000)")
    expected = block[:]
    if active is not None:
        if not 1 <= active <= expected[2]:
            raise DeviceError("palier actif invalide")
        expected[1] = active
    for index, v in enumerate(values):
        o = 3 + index * 7
        old_x = (expected[o + 1] << 8) | expected[o + 2]
        old_y = (expected[o + 3] << 8) | expected[o + 4]
        extra = (expected[o + 5] << 8) | expected[o + 6]
        expected[o + 1:o + 5] = bytes([v >> 8, v & 255, v >> 8, v & 255])
        if old_x == old_y and extra == old_x:
            expected[o + 5:o + 7] = bytes([v >> 8, v & 255])
    return _write_block(expected, block)


def restore_block(hex_block):
    saved = bytearray.fromhex(hex_block)
    if len(saved) != 38:
        raise DeviceError("sauvegarde invalide (38 octets attendus)")
    return _write_block(saved, read_stage_block())


def _write_block(expected, previous):
    if expected == previous:
        return {"changed": False, **decode_stages(previous)}
    transact(4, 0x06, bytes(expected))
    actual = read_stage_block()
    if actual != expected:
        raise DeviceError("RELECTURE DIFFERENTE de la demande\n"
                          f"  demande : {expected.hex()}\n  relu    : {actual.hex()}")
    return {"changed": True, **decode_stages(actual)}


def write_poll(hz):
    code = POLL_ENCODE.get(hz)
    if code is None:
        raise DeviceError("taux de scrutation : 125, 500 ou 1000 Hz uniquement")
    transact(0, 0x05, bytes([code]))
    actual = read_poll()
    if actual != hz:
        raise DeviceError(f"relecture a {actual} Hz au lieu de {hz} Hz")
    return actual


def write_idle(seconds):
    if not 60 <= seconds <= 900:
        raise DeviceError("mise en veille : 60 a 900 secondes")
    transact(7, 0x03, bytes([seconds >> 8, seconds & 255]))
    actual = read_idle()
    if actual != seconds:
        raise DeviceError(f"relecture a {actual} s au lieu de {seconds} s")
    return actual


def write_threshold(percent):
    if not 5 <= percent <= 30:
        raise DeviceError("alerte batterie faible : 5 a 30 %")
    code = round(percent * 255 / 100)
    transact(7, 0x01, bytes([code]))
    actual = read_threshold()
    if actual["raw"] != code:
        raise DeviceError(f"relecture brute {actual['raw']} au lieu de {code}")
    return actual
