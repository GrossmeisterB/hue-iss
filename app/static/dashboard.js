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
    searchQuery: "",

    async geocodeAddress() {
      const q = (this.searchQuery || "").trim();
      if (!q) {
        this.locMsg = "Type a place to search";
        return;
      }
      this.locMsg = "Searching '" + q + "'…";
      const resp = await fetch("/api/location/geocode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q }),
      });
      const data = await resp.json();
      if (resp.ok) {
        this.loc.lat = data.lat;
        this.loc.lon = data.lon;
        this.loc.label = data.label;
        this.locMsg = "✓ Found: " + data.label + " · recomputing passes";
        this.searchQuery = "";
        setTimeout(() => location.reload(), 1500);
      } else {
        this.locMsg = data.error || "No match";
      }
    },

    async saveLocation() {
      this.locMsg = "Saving…";
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
      this.locMsg = resp.ok ? "✓ Saved · recomputing passes" : data.error || "Error";
    },

    useBrowserGeo() {
      if (!navigator.geolocation) {
        this.locMsg = "Browser does not support geolocation";
        return;
      }
      this.locMsg = "Reading GPS…";
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          this.loc.lat = +pos.coords.latitude.toFixed(6);
          this.loc.lon = +pos.coords.longitude.toFixed(6);
          this.loc.label = this.loc.label || "Browser GPS";
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
          this.locMsg = "✓ GPS set · recomputing passes";
        },
        (err) => {
          this.locMsg = "GPS failed: " + err.message + " (needs HTTPS or localhost)";
        },
        { enableHighAccuracy: true, timeout: 15000 }
      );
    },

    async useIpGeo() {
      this.locMsg = "Fetching IP geo…";
      const resp = await fetch("/api/location/ip", { method: "POST" });
      const data = await resp.json();
      if (resp.ok) {
        this.loc.lat = data.lat;
        this.loc.lon = data.lon;
        this.loc.label = data.label;
        this.locMsg = "✓ IP geo set · recomputing passes";
      } else {
        this.locMsg = data.error || "IP geo failed";
      }
    },

    async discoverBridge() {
      this.bridgeMsg = "Searching bridges…";
      const resp = await fetch("/api/bridge/discover", { method: "POST" });
      const data = await resp.json();
      this.discoveredBridges = data;
      this.bridgeMsg = data.length
        ? `${data.length} bridge(s) found`
        : "No bridges found";
    },

    async pairBridge(ip) {
      this.bridgeMsg = `Pairing with ${ip} — press the bridge Link button…`;
      const resp = await fetch("/api/bridge/pair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip }),
      });
      const data = await resp.json();
      if (resp.ok) {
        this.bridgeMsg = "✓ Bridge paired — reloading for lamp list";
        setTimeout(() => location.reload(), 1500);
      } else {
        this.bridgeMsg = "Error: " + (data.error || "unknown");
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
        this.effectMsg = "Error: " + (data.error || "unknown");
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
        this.effectMsg = "Error: " + (data.error || "unknown");
      } else {
        this.effectMsg = "▶ Effect running on selected lamp…";
      }
      setTimeout(() => {
        this.testingEffect = null;
      }, 32000);
    },
  }));
});
