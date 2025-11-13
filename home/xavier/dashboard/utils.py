    # ============================================================================
    # STATUT CARTE SIM / MODEM / PIN
    # ============================================================================

    # --- SIM détectée ? ---
    sim_status = run("qmicli -d /dev/cdc-wdm0 --uim-get-card-status 2>/dev/null")
    sim_ok = "card" in sim_status.lower() or "slot" in sim_status.lower()
    add("SIM : Détection carte", sim_ok, sim_status if sim_status != "N/A" else "")

    # --- Code PIN ---
    pin_raw = run("qmicli -d /dev/cdc-wdm0 --uim-get-pin-status 2>/dev/null")
    if "PIN1" in pin_raw:
        if "enabled" in pin_raw.lower():
            add("SIM : PIN requis", False, pin_raw)
        else:
            add("SIM : PIN OK", True, pin_raw)
    else:
        add("SIM : PIN (info)", False, pin_raw)

    # --- Modem enregistré au réseau ---
    serving = run("qmicli -d /dev/cdc-wdm0 --nas-get-serving-system 2>/dev/null")
    registered = any(k in serving.lower() for k in ["registered", "camped", "attached"])
    add("Modem : Enregistrement réseau", registered, serving)

    # --- APN actif / Data ---
    wwan = run("ip a show wwan0 2>/dev/null")
    data_ok = "state up" in wwan.lower() or "inet " in wwan.lower()
    add("Modem : Interface wwan0 active", data_ok, wwan)
