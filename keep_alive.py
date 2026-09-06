"""A tiny HTTP server so free hosts (like Render) that require a bound port see the service as healthy,
and so an external uptime-pinger has something to hit to stop the service spinning down. See README.md."""

import logging

from aiohttp import web

log = logging.getLogger("keep_alive")


async def _health(request):
    return web.Response(text="OK - bot is running")


async def start_keep_alive_server(port: int):
    app = web.Application()
    app.add_routes([web.get("/", _health), web.get("/health", _health)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Keep-alive web server listening on port %s", port)
    return runner
