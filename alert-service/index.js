const express = require("express");
const os = require("os");

const PORT = process.env.PORT || 8003;
const START_TIME = Date.now();

const app = express();

app.get("/api/health", (req, res) => {
  res.json({
    status: "healthy",
    uptime_seconds: Math.round((Date.now() - START_TIME) / 1000),
    platform: `${os.type()}-${os.release()}-${os.arch()}`,
    node_version: process.version,
  });
});

app.listen(PORT, () => {
  console.log(`[alert-service] escuchando en el puerto ${PORT}`);
});
