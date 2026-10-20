// Run: npm test (from mobile/)   (checks the voice/typed command parser)
const { parse } = require("../www/commands.js");
const APPS = [
  { id: "tvinput.hdmi1", type: "tvin", name: "PlayStation 5" }, { id: "tvinput.hdmi2", type: "tvin", name: "Mac" },
  { id: "tvinput.dtv", type: "tvin", name: "Live TV" }, { id: "12", type: "appl", name: "Netflix" },
  { id: "837", type: "appl", name: "YouTube" }, { id: "13", type: "appl", name: "Prime Video" },
  { id: "551012", type: "appl", name: "Apple TV" }, { id: "34376", type: "appl", name: "ESPN" },
  { id: "151908", type: "appl", name: "The Roku Channel" }, { id: "13842", type: "appl", name: "Fandango" },
];
const cases = [
  ["volume up", { key: "VolumeUp", times: 3 }], ["louder 5", { key: "VolumeUp", times: 5 }],
  ["turn it down two", { key: "VolumeDown", times: 2 }], ["mute", { key: "VolumeMute" }],
  ["turn off the tv", { key: "PowerOff" }], ["turn on the tv", { key: "PowerOn" }],
  ["go home", { key: "Home" }], ["back", { key: "Back" }], ["options", { key: "Info" }],
  ["pause", { key: "Pause" }], ["resume", { key: "Play" }], ["down 3", { key: "Down", times: 3 }],
  ["ok", { key: "Select" }], ["open netflix", { launch: "12" }], ["youtube", { launch: "837" }],
  ["switch to playstation", { launch: "tvinput.hdmi1" }], ["open fandango", { launch: "13842" }],
  ["hdmi 2", { launch: "tvinput.hdmi2" }],
  ["play stranger things on netflix", { search: "stranger things", launch: true, provider: "12" }],
  ["search for interstellar", { search: "interstellar", launch: false }],
  ["type breaking bad", { type: "breaking bad" }], ["Interstellar", { search: "Interstellar", launch: true }],
  ["play youtube", { launch: "837" }],
  ["громче", { key: "VolumeUp", times: 3 }], ["сделай тише пять", { key: "VolumeDown", times: 5 }],
  ["выключи звук", { key: "VolumeMute" }], ["выключи телевизор", { key: "PowerOff" }],
  ["включи телевизор", { key: "PowerOn" }], ["домой", { key: "Home" }], ["назад", { key: "Back" }],
  ["пауза", { key: "Pause" }], ["вниз два раза", { key: "Down", times: 2 }], ["ок", { key: "Select" }],
  ["открой ютуб", { launch: "837" }], ["запусти нетфликс", { launch: "12" }],
  ["включи плейстейшн", { launch: "tvinput.hdmi1" }], ["переключи на мак", { launch: "tvinput.hdmi2" }],
  ["включи интерстеллар на нетфликсе", { search: "интерстеллар", launch: true, provider: "12" }],
  ["найди мстители", { search: "мстители", launch: false }], ["напиши привет", { type: "привет" }],
  ["звездочка", { key: "Info" }], ["перемотай вперед", { key: "Fwd", times: 1 }],
];
let fail = 0;
for (const [say, want] of cases) {
  const p = parse(say, APPS); const got = p && p.steps[0];
  const ok = got && Object.entries(want).every(([k, v]) => String(got[k]) === String(v));
  if (!ok) fail++;
  console.log(`${ok ? "ok  " : "FAIL"} ${say.padEnd(36)} -> ${p ? p.label : "null"}${ok ? "" : "   got " + JSON.stringify(got)}`);
}
console.log(`\n${cases.length - fail}/${cases.length} passed`);
process.exit(fail ? 1 : 0);
