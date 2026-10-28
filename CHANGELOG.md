# Changelog

## 0.1.0 (2026-10-29)

The first version, by InfiArtt.

- `Bot` with decorators (`@bot.command`, `@bot.event`, `@bot.dialog`, `@bot.action`) or a subclass
  (`on_*` methods, `@command`, `@suggest`).
- The gateway connection: identify, heartbeats, resume per server, connecting again with growing waits,
  rate limits waited out, and a stop on a changed token or a second connection.
- Commands with fields read from the handler's parameters, values converted, suggestions, and who may use them.
- Interactions with the 3-second rule kept by an automatic defer.
- Dialogs with every control of InfiTalk, checked like the server checks them, plus message buttons and forms.
- Audio paced in real time: PCM, files through ffmpeg, a quiet tone, volume, stop.
- `infitalk.testing.TestServer` to test a bot without a server.
