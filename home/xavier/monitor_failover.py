def switch_to_4g():
    if not is_4g_connected():
        log("Connexion 4G...")
        subprocess.run(["sudo", CONNECT_4G])

    log("Bascule sur 4G")

    # Suppression route Freebox si elle existe
    subprocess.run(["ip", "route", "del", "default", "via", GATEWAY, "dev", "eth0"], stderr=subprocess.DEVNULL)

    # Récupérer gateway wwan0
    route = subprocess.run(["ip", "route", "show", "dev", "wwan0"], capture_output=True, text=True).stdout
    if "default" not in route:
        log("ERREUR : Aucune route 4G trouvée", LOG_FILE)
        return

    gw_4g = route.split("via")[1].split()[0]

    subprocess.run(["ip", "route", "add", "default", "via", gw_4g, "dev", "wwan0"])

    try:
        subprocess.run(["python3", SMS_SCRIPT, "Failover: Bascule sur 4G !"])
    except:
        log("ERREUR SMS failover", LOG_FILE)

    update_history(0)
