/*
 * Remoot voice / typed command parser (English + Russian).
 * Pure function: text + list of TV apps -> plan of ECP actions. No I/O here,
 * so it runs in Node for tests (see scripts/test_commands.js).
 *
 * Plan shape: { label, steps: [ {key, times} | {launch, name} | {type: "text"}
 *                                | {search, launch, provider} ] }
 */
(function (root) {
  const NUM = {
    one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
    a: 1, once: 1, twice: 2, couple: 2, few: 3, lot: 6,
    "один": 1, "одна": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "раз": 1,
  };

  // Spoken names -> words that appear in the TV's own app names.
  const ALIASES = [
    [/(?<![a-zа-я0-9])(netflix|нетфликс[a-zа-я]*|нэтфликс[a-zа-я]*)/, "netflix"],
    [/(?<![a-zа-я0-9])(you ?tube|ютуб[a-zа-я]*|ютюб[a-zа-я]*)/, "youtube"],
    [/(?<![a-zа-я0-9])(prime( video)?|amazon|прайм[a-zа-я]*|амазон[a-zа-я]*)/, "prime video"],
    [/(?<![a-zа-я0-9])(disney\+?|disney plus|дисней[a-zа-я]*)/, "disney"],
    [/(?<![a-zа-я0-9])(hulu|хулу)/, "hulu"],
    [/(?<![a-zа-я0-9])(paramount\+?|парамаунт[a-zа-я]*)/, "paramount"],
    [/(?<![a-zа-я0-9])(apple ?tv|эпл ?тв|эппл ?тв|апл ?тв)/, "apple tv"],
    [/(?<![a-zа-я0-9])(espn|еспн|эспн)/, "espn"],
    [/(?<![a-zа-я0-9])(roku channel|року)/, "roku channel"],
    [/(?<![a-zа-я0-9])(play ?station|ps ?5|плейстейшн[a-zа-я]*|плэйстейшн[a-zа-я]*|пс ?5)/, "playstation"],
    [/(?<![a-zа-я0-9])(live tv|антенн[a-zа-я]*|эфир[a-zа-я]*|тв канал[a-zа-я]*)/, "live tv"],
    [/(?<![a-zа-я0-9])(spotify|спотифай)/, "spotify"],
    [/(?<![a-zа-я0-9])(twitch|твич)/, "twitch"],
    [/(?<![a-zа-я0-9])(max|hbo|эйчбио|хбо)(?![a-zа-я0-9])/, "max"],
    [/(?<![a-zа-я0-9])(mac|мак|макбук|macbook)(?![a-zа-я0-9])/, "mac"],
    [/(?<![a-zа-я0-9])hdmi ?(1|one|один)(?![a-zа-я0-9])/, "hdmi1"],
    [/(?<![a-zа-я0-9])hdmi ?(2|two|два)(?![a-zа-я0-9])/, "hdmi2"],
    [/(?<![a-zа-я0-9])hdmi ?(3|three|три)(?![a-zа-я0-9])/, "hdmi3"],
  ];

  const PROVIDER_IDS = { netflix: "12", youtube: "837", "prime video": "13", paramount: "31440",
    disney: "291097", hulu: "2285", "apple tv": "551012" };

  function norm(s) {
    return String(s || "").toLowerCase().replace(/ё/g, "е")
      .replace(/[“”"«»!?.,;:]/g, " ").replace(/\s+/g, " ").trim();
  }

  function count(t, dflt) {
    const d = t.match(/(?<![a-zа-я0-9])(\d{1,2})(?![a-zа-я0-9])/);
    if (d) return Math.max(1, Math.min(20, parseInt(d[1], 10)));
    for (const w of t.split(" ")) if (NUM[w] && w !== "a") return NUM[w];
    return dflt;
  }

  /** Find the TV app the words refer to. apps: [{id, name, type}] */
  function matchApp(words, apps) {
    const t = norm(words);
    if (!t) return null;
    let want = null;
    for (const [re, canon] of ALIASES) if (re.test(t)) { want = canon; break; }
    const list = apps || [];
    const byName = (n) => norm(n).replace(/[^a-z0-9а-я+ ]/g, "");
    if (want) {
      if (/^hdmi\d$/.test(want)) {
        const hit = list.find((a) => a.id === "tvinput." + want);
        if (hit) return hit;
      }
      const exact = list.find((a) => byName(a.name) === want);
      if (exact) return exact;
      const part = list.find((a) => byName(a.name).includes(want));
      if (part) return part;
      if (PROVIDER_IDS[want]) return { id: PROVIDER_IDS[want], name: want, guessed: true };
    }
    // Plain match on the TV's own names ("open fandango").
    const cleaned = t.replace(/(?<![a-zа-я0-9])(the|app|channel|приложение|канал)(?![a-zа-я0-9])/g, "").trim();
    if (cleaned.length >= 3) {
      const exact = list.find((a) => byName(a.name) === cleaned);
      if (exact) return exact;
      const starts = list.find((a) => byName(a.name).startsWith(cleaned));
      if (starts) return starts;
      if (cleaned.length >= 4) {
        const inc = list.find((a) => byName(a.name).includes(cleaned));
        if (inc) return inc;
      }
    }
    return null;
  }

  function key(k, times = 1) { return { key: k, times }; }

  function parse(text, apps) {
    const raw = String(text || "").trim();
    const t = norm(raw);
    if (!t) return null;
    const plan = (label, ...steps) => ({ label, steps });

    // Type text into a TV keyboard: "type breaking bad", "напиши привет"
    let m = raw.match(/^\s*(type|write|enter text|напиши|набери|введи)\s+(.+)$/i);
    if (m) return plan(`Type “${m[2]}”`, { type: m[2] });

    // Mute before power/volume, since "выключи звук" contains "выключи"
    if (/(?<![a-zа-я0-9])(unmute|mute|silence)(?![a-zа-я0-9])|без звука|выключи звук|включи звук|верни звук|отключи звук|заглуши/.test(t))
      return plan("Mute", key("VolumeMute"));

    // Power
    if (/(?<![a-zа-я0-9])(turn|switch|power|shut)(?![a-zа-я0-9]).*(?<![a-zа-я0-9])off(?![a-zа-я0-9])|(?<![a-zа-я0-9])power off(?![a-zа-я0-9])|(?<![a-zа-я0-9])shut down(?![a-zа-я0-9])|^off$|^(выключи|выключить|отключи)( телевизор| тв| телик)?$|выключи телевизор|выключи тв/.test(t))
      return plan("Power off", key("PowerOff"));
    if (/(?<![a-zа-я0-9])(turn|switch|power)(?![a-zа-я0-9]).*(?<![a-zа-я0-9])on(?![a-zа-я0-9])( the)?( tv)?$|(?<![a-zа-я0-9])power on(?![a-zа-я0-9])|^(включи|включить)( телевизор| тв| телик)$|^wake up/.test(t))
      return plan("Power on", key("PowerOn"));

    // Volume
    if (/(?<![a-zа-я0-9])(volume up|louder|turn it up|turn up|increase volume|raise volume)(?![a-zа-я0-9])|громче|прибавь|сделай громче|погромче/.test(t)) {
      const n = count(t, 3); return plan(`Volume + ×${n}`, key("VolumeUp", n));
    }
    if (/(?<![a-zа-я0-9])(volume down|quieter|softer|turn it down|turn down|lower volume|decrease volume)(?![a-zа-я0-9])|тише|убавь|сделай тише|потише/.test(t)) {
      const n = count(t, 3); return plan(`Volume − ×${n}`, key("VolumeDown", n));
    }

    // Simple keys
    if (/^(go )?(home|home screen)$|^(go to )?home screen$|^go home$|домой|на главную|главный экран|главное меню/.test(t)) return plan("Home", key("Home"));
    if (/^(go )?back$|^go back$|^назад$|^вернись|^вернуться|^обратно/.test(t)) return plan("Back", key("Back"));
    if (/(?<![a-zа-я0-9])(options|star|asterisk|info)(?![a-zа-я0-9])|звездочк|опции|параметры/.test(t)) return plan("✱ Options", key("Info"));
    if (/(?<![a-zа-я0-9])(instant replay|replay)(?![a-zа-я0-9])|повтори|еще раз/.test(t)) return plan("Replay", key("InstantReplay"));
    if (/^(pause|stop|hold on|wait)( it| this| the (movie|show|video))?$|^(пауза|стоп|останови|поставь на паузу|на паузу)/.test(t)) return plan("Pause", key("Pause"));
    if (/^(play|resume|continue|unpause|keep playing)( it| this)?$|^(продолжи|продолжай|играй|воспроизведи|сними с паузы|дальше)$/.test(t)) return plan("Play / pause", key("Play"));
    if (/(?<![a-zа-я0-9])(rewind|go back \d+|skip back)(?![a-zа-я0-9])|перемотай назад|отмотай|назад на/.test(t)) { const n = count(t, 1); return plan(`Rewind ×${n}`, key("Rev", n)); }
    if (/(?<![a-zа-я0-9])(fast forward|forward|skip ahead|skip forward)(?![a-zа-я0-9])|перемотай вперед|перемотай|вперед на/.test(t)) { const n = count(t, 1); return plan(`Fast-forward ×${n}`, key("Fwd", n)); }
    if (/^(search|open search)$|^поиск$/.test(t)) return plan("Search", key("Search"));

    // D-pad: "down", "down 3", "вниз два раза", "ok"
    const NAV = [
      [/^(up|move up|go up)(?![a-zа-я0-9])|^(вверх|наверх)(?![a-zа-я0-9])/, "Up"], [/^(down|move down|go down)(?![a-zа-я0-9])|^(вниз)(?![a-zа-я0-9])/, "Down"],
      [/^(left|move left|go left)(?![a-zа-я0-9])|^(влево|налево)(?![a-zа-я0-9])/, "Left"], [/^(right|move right|go right)(?![a-zа-я0-9])|^(вправо|направо)(?![a-zа-я0-9])/, "Right"],
      [/^(ok|okay|select|enter|choose|click|press ok)$|^(ок|окей|выбери|выбрать|нажми|ввод)$/, "Select"],
    ];
    for (const [re, k] of NAV) if (re.test(t)) {
      const n = k === "Select" ? 1 : count(t, 1);
      return plan(n > 1 ? `${k} ×${n}` : k, key(k, n));
    }

    // "search for X", "find X", "найди X"
    m = raw.match(/^\s*(search for|search|find|look up|look for|найди|поищи|ищи|поиск)\s+(.+)$/i);
    if (m) return plan(`Search “${m[2]}”`, { search: m[2], launch: false });

    // "open netflix", "launch youtube", "открой ютуб", "запусти плейстейшн", "switch to hdmi 1"
    m = t.match(/^(open|launch|start|go to|switch to|change to|input|открой|запусти|переключи на|переключись на|зайди в|вруби)\s+(.+)$/);
    if (m) {
      const app = matchApp(m[2], apps);
      if (app) return plan(`Open ${app.name}`, { launch: app.id, name: app.name });
      return plan(`Search “${m[2]}”`, { search: m[2], launch: false });
    }

    // "play X on netflix", "включи X на ютубе", "watch X"
    m = raw.match(/^\s*(play|watch|put on|show me|включи|поставь|покажи|запусти)\s+(.+?)(\s+(on|in|на|в)\s+(.+))?\s*$/i);
    if (m) {
      const what = m[2];
      const where = m[5] ? matchApp(m[5], apps) : null;
      const whole = !m[5] ? matchApp(what, apps) : null;
      if (whole) return plan(`Open ${whole.name}`, { launch: whole.id, name: whole.name });
      if (where) return plan(`Play “${what}” on ${where.name}`, { search: what, launch: true, provider: where.id });
      return plan(`Play “${m[5] ? what + " " + m[4] + " " + m[5] : what}”`, { search: m[5] ? `${what} ${m[4]} ${m[5]}` : what, launch: true });
    }

    // Just an app name: "netflix", "ютуб"
    const app = matchApp(t, apps);
    if (app) return plan(`Open ${app.name}`, { launch: app.id, name: app.name });

    // Anything else: treat as a title to find and play.
    return plan(`Play “${raw}”`, { search: raw, launch: true });
  }

  const api = { parse, matchApp, norm };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RemootCommands = api;
})(typeof window !== "undefined" ? window : globalThis);
