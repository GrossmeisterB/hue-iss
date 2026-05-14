document.addEventListener("alpine:init", () => {
  const bootstrap = JSON.parse(
    document.getElementById("bootstrap-data").textContent
  );

  Alpine.data("dashboard", () => ({
    loc: {
      lat: bootstrap.loc.lat,
      lon: bootstrap.loc.lon,
      label: bootstrap.loc.label || "",
    },
    config: {
      light_id: bootstrap.config.light_id,
      effect_name: bootstrap.config.effect_name,
    },
    discoveredBridges: [],
    bridgeMsg: "",
    locMsg: "",
    effectMsg: "",
    testingEffect: null,

    async saveLocation() {
      this.locMsg = "Speichere…";
      const resp = await fetch("/api/location", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lat: this.loc.lat,
          lon: this.loc.lon,
          label: this.loc.label,
          source: "manual_pin",
        }),
      });
      const data = await resp.json();
      this.locMsg = resp.ok ? "✓ Gespeichert · Pässe werden neu berechnet" : data.error || "Fehler";
    },

    useBrowserGeo() {
      if (!navigator.geolocation) {
        this.locMsg = "Browser unterstützt keine Geolocation";
        return;
      }
      this.locMsg = "Hole GPS…";
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          this.loc.lat = +pos.coords.latitude.toFixed(6);
          this.loc.lon = +pos.coords.longitude.toFixed(6);
          this.loc.label = this.loc.label || "Browser-GPS";
          await fetch("/api/location", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              lat: this.loc.lat,
              lon: this.loc.lon,
              label: this.loc.label,
              source: "browser_geo",
            }),
          });
          this.locMsg = "✓ GPS gesetzt · Pässe werden neu berechnet";
        },
        (err) => {
          this.locMsg = "GPS fehlgeschlagen: " + err.message + " (HTTPS oder localhost nötig)";
        },
        { enableHighAccuracy: true, timeout: 15000 }
      );
    },

    async useIpGeo() {
      this.locMsg = "Hole IP-Geo…";
      const resp = await fetch("/api/location/ip", { method: "POST" });
      const data = await resp.json();
      if (resp.ok) {
        this.loc.lat = data.lat;
        this.loc.lon = data.lon;
        this.loc.label = data.label;
        this.locMsg = "✓ IP-Geo gesetzt · Pässe werden neu berechnet";
      } else {
        this.locMsg = data.error || "IP-Geo fehlgeschlagen";
      }
    },

    async discoverBridge() {
      this.bridgeMsg = "Suche Bridges…";
      const resp = await fetch("/api/bridge/discover", { method: "POST" });
      const data = await resp.json();
      this.discoveredBridges = data;
      this.bridgeMsg = data.length
        ? `${data.length} Bridge(s) gefunden`
        : "Keine Bridges gefunden";
    },

    async pairBridge(ip) {
      this.bridgeMsg = `Pairing mit ${ip} — drücke den Link-Button…`;
      const resp = await fetch("/api/bridge/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip }),
      });
      const data = await resp.json();
      if (resp.ok) {
        this.bridgeMsg = "✓ Bridge gepairt — Seite neu laden für Lampenliste";
        setTimeout(() => location.reload(), 1500);
      } else {
        this.bridgeMsg = "Fehler: " + (data.error || "unbekannt");
      }
    },

    async saveConfig() {
      const resp = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(this.config),
      });
      if (!resp.ok) {
        const data = await resp.json();
        this.effectMsg = "Fehler: " + (data.error || "unbekannt");
      }
    },

    async testEffect(name) {
      this.effectMsg = "";
      this.testingEffect = name;
      const resp = await fetch("/api/effect/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ effect_name: name, light_id: this.config.light_id }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        this.effectMsg = "Fehler: " + (data.error || "unbekannt");
      } else {
        this.effectMsg = "▶ Effekt läuft auf gewählter Lampe…";
      }
      setTimeout(() => {
        this.testingEffect = null;
      }, 32000);
    },
  }));
});
