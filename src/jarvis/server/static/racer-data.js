"use strict";
// Kerbside Grand Prix: the game's data. Cars, upgrades, drivers and their personalities, districts, events, the
// five-chapter story (dialogue, choices, consequences) and achievements. Plain data, no logic beyond small helpers;
// racer-career.js turns it into progression and racer-ui.js presents it. Everything here is original to this game.
(function (root) {
  // ---------------------------------------------------------------- Cars
  // Physics stats feed racer.js: acc (units/s²), drag (top speed = acc / drag), grip (tyre damping), brake, steer,
  // nitro {push, burn, fill, cap}. shape picks the drawing; class sets prices and upgrade costs.
  // Physics stats feed racer.js: acc (units/s²), drag (top speed = acc / drag), grip (tyre damping), brake, steer,
  // nitro {push, burn, fill, cap}, mass (collisions: heavier cars shove lighter ones), and traits: slide (0–1, a car
  // that likes to drift), turbo (power that builds with lag), offroad (less slowed on grass and gravel), wet (rain
  // grip). shape picks the drawing; cls sets prices and upgrade costs; cat is the car's family; unlock says how to
  // get it (story rewards, a chapter, a rival beaten, reputation or the end of the story). price null: not for sale.
  const N = (push, burn, fill, cap) => ({ push, burn, fill, cap });
  const CARS = {
    // ---- Class C: where everyone starts
    pacer: { name: "Okafor Pacer", cls: "C", cat: "Club racer", shape: "open", price: 0, blurb: "Nia's rebuilt club racer. Light, honest, a little slow.",
      acc: 405, drag: 0.66, grip: 6.3, brake: 900, steer: 2.7, mass: 0.9, nitro: N(340, 0.42, 0.052, 1.25) },
    kitsune: { name: "Kitsune Kei", cls: "C", cat: "Compact tuner", shape: "kei", price: 2400, unlock: { chapter: 1 }, blurb: "A tiny kei car with a big attitude. Darts through hairpins, hates long straights.",
      acc: 392, drag: 0.67, grip: 7.1, brake: 940, steer: 3.05, mass: 0.75, nitro: N(300, 0.4, 0.062, 1.24) },
    mistral: { name: "Mistral Hatch", cls: "C", cat: "Rally hatch", shape: "rally", price: 3200, blurb: "A rally hatch that grips in the wet and forgives everything.",
      acc: 412, drag: 0.68, grip: 7.0, brake: 920, steer: 2.85, mass: 0.95, wet: 0.08, offroad: 0.3, nitro: N(330, 0.4, 0.056, 1.24) },
    vela: { name: "Vela GTi", cls: "C", cat: "Hot hatch", shape: "hatch", price: 3600, unlock: { chapter: 2 }, blurb: "The everyday hot hatch: quick off the line, tidy in the bends.",
      acc: 420, drag: 0.67, grip: 6.6, brake: 930, steer: 2.85, mass: 0.95, nitro: N(340, 0.41, 0.056, 1.25) },
    ronin: { name: "Ronin RS", cls: "C", cat: "Japanese sports", shape: "coupe", price: 4200, unlock: { chapter: 2 }, blurb: "Rear-drive coupe built for going sideways. The drifters' favourite.",
      acc: 420, drag: 0.665, grip: 6.1, brake: 910, steer: 2.95, mass: 1.0, slide: 0.45, nitro: N(350, 0.42, 0.055, 1.25) },
    dune: { name: "Dune Runner", cls: "C", cat: "Rally raider", shape: "rally", price: 3900, unlock: { rep: 40 }, blurb: "Long-travel suspension. Barely notices the gravel trap.",
      acc: 410, drag: 0.69, grip: 6.8, brake: 900, steer: 2.8, mass: 1.05, offroad: 0.6, wet: 0.05, nitro: N(330, 0.42, 0.055, 1.24) },
    // ---- Class B
    kestrel: { name: "Kestrel GT", cls: "B", cat: "Grand tourer", shape: "gt", price: 6800, blurb: "Balanced grand tourer. Quick everywhere, best nowhere.",
      acc: 440, drag: 0.64, grip: 6.6, brake: 950, steer: 2.75, mass: 1.15, nitro: N(370, 0.4, 0.055, 1.27) },
    brute: { name: "Brute V8", cls: "B", cat: "American muscle", shape: "muscle", price: 7400, blurb: "Huge straight-line speed, heavy in the bends.",
      acc: 478, drag: 0.65, grip: 5.7, brake: 860, steer: 2.5, mass: 1.35, nitro: N(420, 0.44, 0.05, 1.3) },
    ardent: { name: "Ardent 8", cls: "B", cat: "European sports sedan", shape: "sedan", price: 6200, unlock: { chapter: 2 }, blurb: "A four-door that embarrasses coupes. Superb brakes.",
      acc: 445, drag: 0.655, grip: 6.5, brake: 1000, steer: 2.7, mass: 1.15, nitro: N(360, 0.4, 0.056, 1.26) },
    longhaul: { name: "Longhaul Estate", cls: "B", cat: "Sleeper wagon", shape: "wagon", price: 5600, unlock: { rep: 60 }, blurb: "A family estate with a race engine. Nobody expects it.",
      acc: 452, drag: 0.665, grip: 6.3, brake: 950, steer: 2.6, mass: 1.25, nitro: N(380, 0.42, 0.054, 1.27) },
    hayate: { name: "Hayate GT-R", cls: "B", cat: "Japanese sports", shape: "coupe", price: 7800, unlock: { chapter: 3 }, blurb: "Twin turbos and four-wheel grip. Brutal once the boost arrives.",
      acc: 448, drag: 0.65, grip: 6.9, brake: 990, steer: 2.8, mass: 1.1, turbo: 0.08, wet: 0.05, nitro: N(370, 0.4, 0.056, 1.27) },
    lumen: { name: "Lumen Roadster", cls: "B", cat: "Roadster", shape: "roadster", price: 6900, unlock: { chapter: 3 }, blurb: "Light, open-top, and it changes direction like a thought.",
      acc: 430, drag: 0.645, grip: 7.2, brake: 1000, steer: 3.0, mass: 0.85, nitro: N(350, 0.4, 0.058, 1.26) },
    stallion: { name: "Stallion 302", cls: "B", cat: "American muscle", shape: "muscle", price: 7200, unlock: { chapter: 3 }, blurb: "Pure drag-strip muscle. Point it straight and hold on.",
      acc: 488, drag: 0.66, grip: 5.5, brake: 840, steer: 2.45, mass: 1.35, nitro: N(440, 0.44, 0.05, 1.31) },
    // ---- Class A
    halcyon: { name: "Halcyon F2", cls: "A", cat: "Track single-seater", shape: "open", price: 12500, blurb: "A proper single-seater. Brakes late, turns in sharp.",
      acc: 462, drag: 0.645, grip: 7.3, brake: 1020, steer: 2.9, mass: 0.8, nitro: N(380, 0.4, 0.056, 1.28) },
    corvid: { name: "Corvid LMP", cls: "A", cat: "Prototype", shape: "proto", price: 14800, blurb: "Endurance prototype. Fast and stable, needs commitment.",
      acc: 480, drag: 0.64, grip: 6.9, brake: 990, steer: 2.75, mass: 0.95, nitro: N(400, 0.38, 0.058, 1.3) },
    vespera: { name: "Vespera GT3", cls: "A", cat: "European GT", shape: "gt", price: 13800, unlock: { chapter: 4 }, blurb: "A racing GT on road tyres. Planted, precise, expensive.",
      acc: 470, drag: 0.64, grip: 7.4, brake: 1040, steer: 2.85, mass: 1.15, nitro: N(390, 0.4, 0.057, 1.28) },
    tempest: { name: "Tempest Evo", cls: "A", cat: "Rally icon", shape: "rally", price: 12000, unlock: { rep: 140 }, blurb: "All-wheel-drive rally weapon. Untouchable in the rain.",
      acc: 466, drag: 0.655, grip: 7.3, brake: 1010, steer: 3.0, mass: 1.0, wet: 0.14, offroad: 0.4, turbo: 0.05, nitro: N(380, 0.4, 0.058, 1.28) },
    goliath: { name: "Goliath SC", cls: "A", cat: "American muscle", shape: "muscle", price: 13000, unlock: { chapter: 4 }, blurb: "Supercharged and furious. The quickest thing in a straight line under a hypercar.",
      acc: 505, drag: 0.655, grip: 6.0, brake: 900, steer: 2.5, mass: 1.45, nitro: N(470, 0.44, 0.05, 1.32) },
    kaze: { name: "Kaze Type-S", cls: "A", cat: "Japanese supercar", shape: "super", price: 14500, unlock: { chapter: 4 }, blurb: "Mid-engined and balanced. Rewards a smooth driver.",
      acc: 478, drag: 0.642, grip: 7.2, brake: 1030, steer: 2.95, mass: 1.05, turbo: 0.04, nitro: N(390, 0.39, 0.058, 1.29) },
    // ---- Class S
    sirocco: { name: "Sirocco S1", cls: "S", cat: "Hypercar", shape: "proto", price: 23000, blurb: "Hypercar wedge with an enormous nitro tank.",
      acc: 500, drag: 0.635, grip: 7.1, brake: 1040, steer: 2.85, mass: 1.05, nitro: N(440, 0.34, 0.062, 1.33) },
    aurora: { name: "Aurora V12", cls: "S", cat: "Supercar", shape: "super", price: 26000, unlock: { chapter: 5 }, blurb: "Twelve cylinders, scissor doors, no apologies.",
      acc: 518, drag: 0.635, grip: 7.1, brake: 1050, steer: 2.75, mass: 1.2, nitro: N(430, 0.36, 0.06, 1.32) },
    spectre: { name: "Spectre Hyper", cls: "S", cat: "Hypercar", shape: "super", price: 32000, unlock: { ended: true }, blurb: "The fastest road car in Port Kerbside. Handle with respect.",
      acc: 535, drag: 0.63, grip: 7.3, brake: 1080, steer: 2.8, mass: 1.15, turbo: 0.05, nitro: N(450, 0.35, 0.06, 1.34) },
    phantom: { name: "Phantom LMP1", cls: "S", cat: "Track prototype", shape: "proto", price: 30000, unlock: { ended: true }, blurb: "A Le Mans-style prototype with lights fitted. Corners like it's on rails.",
      acc: 522, drag: 0.628, grip: 7.8, brake: 1100, steer: 2.9, mass: 0.95, nitro: N(420, 0.35, 0.062, 1.32) },
    countess: { name: "Corsa Contessa", cls: "S", cat: "Champion's GT", shape: "gt", price: null, blurb: "Valentina Corsa's championship car. Not for sale.",
      acc: 512, drag: 0.632, grip: 7.4, brake: 1060, steer: 2.9, mass: 1.1, nitro: N(430, 0.36, 0.06, 1.32) },
    // ---- Rival signature cars: beat the rival three times and they'll sell you one of their own
    ironclad: { name: "Ironclad Brute R", cls: "B", cat: "Rival signature (Dex)", shape: "muscle", price: 9000, unlock: { rival: "dex", wins: 3 }, blurb: "Dex's own build: stripped, caged, louder than legal.",
      acc: 496, drag: 0.655, grip: 5.9, brake: 880, steer: 2.55, mass: 1.3, nitro: N(470, 0.42, 0.052, 1.31) },
    tidewater: { name: "Tidewater Mistral R", cls: "B", cat: "Rival signature (Mara)", shape: "rally", price: 8500, unlock: { rival: "mara", wins: 3 }, blurb: "Mara's harbour car: grips like a limpet, wet or dry.",
      acc: 448, drag: 0.66, grip: 7.5, brake: 1000, steer: 3.0, mass: 0.95, wet: 0.12, nitro: N(360, 0.4, 0.058, 1.27) },
    brickyard: { name: "Brickyard Kestrel", cls: "B", cat: "Rival signature (Benny)", shape: "gt", price: 9500, unlock: { rival: "benny", wins: 3 }, blurb: "Benny's night-race GT. The nitro refills suspiciously fast.",
      acc: 462, drag: 0.65, grip: 6.9, brake: 980, steer: 2.8, mass: 1.1, nitro: N(390, 0.38, 0.07, 1.29) },
    summit: { name: "Summit Halcyon S", cls: "A", cat: "Rival signature (Sora)", shape: "open", price: 16000, unlock: { rival: "sora", wins: 3 }, blurb: "Sora's engineering masterpiece. Every tenth accounted for.",
      acc: 478, drag: 0.64, grip: 7.7, brake: 1080, steer: 2.95, mass: 0.8, nitro: N(390, 0.38, 0.058, 1.29) },
    // ---- Police (pursuit mode only)
    interceptor: { name: "PKPD Interceptor", cls: "A", cat: "Police", shape: "sedan", price: null, police: true, blurb: "Port Kerbside Police. Heavy, fast, relentless.",
      acc: 492, drag: 0.645, grip: 6.9, brake: 1000, steer: 2.8, mass: 1.5, nitro: N(420, 0.4, 0.06, 1.3) },
    // the new generation: Japanese tuners, European exotics, American muscle and a pickup, a classic and an electric
    kurogane: { name: "Kurogane Drift Spec", cls: "B", cat: "Japanese drift special", shape: "coupe", price: 8200, unlock: { achievement: "drifter" }, blurb: "Built in a Ridge garage for one thing: going sideways. Earned by drifters only.",
      acc: 452, drag: 0.655, grip: 6.0, brake: 960, steer: 3.05, mass: 1.0, turbo: 0.08, slide: 0.6, nitro: N(360, 0.42, 0.06, 1.26) },
    tsubame: { name: "Tsubame Time Attack", cls: "A", cat: "Japanese time-attack", shape: "coupe", price: 15500, unlock: { medals: 2 }, blurb: "A time-attack car with a wing like a dining table. For people who collect gold medals.",
      acc: 468, drag: 0.652, grip: 7.6, brake: 1040, steer: 2.95, mass: 1.05, turbo: 0.1, nitro: N(380, 0.4, 0.056, 1.28) },
    valkyrie: { name: "Valkyrie SV", cls: "A", cat: "European mid-engined", shape: "super", price: 15200, unlock: { chapter: 4 }, blurb: "A mid-engined V10 that screams past nine thousand revs. Balanced and exotic.",
      acc: 482, drag: 0.64, grip: 7.1, brake: 1030, steer: 3.02, mass: 1.02, slide: 0.12, nitro: N(390, 0.38, 0.058, 1.29) },
    montecarlo: { name: "Montecarlo GT12", cls: "S", cat: "European V12 tourer", shape: "gt", price: 29000, unlock: { ended: true }, blurb: "Twelve cylinders, two seats, all the torque in the world. Arrives, never hurries.",
      acc: 515, drag: 0.633, grip: 7.2, brake: 1050, steer: 2.62, mass: 1.4, wet: 0.05, nitro: N(420, 0.37, 0.058, 1.31) },
    feather: { name: "Feather 7", cls: "B", cat: "European lightweight", shape: "roadster", price: 7600, unlock: { rep: 120 }, blurb: "Weighs less than a motorbike and a friend. Barely any power, almost endless grip.",
      acc: 422, drag: 0.64, grip: 7.6, brake: 1020, steer: 3.1, mass: 0.7, nitro: N(350, 0.42, 0.058, 1.26) },
    thunderbolt: { name: "Thunderbolt '69", cls: "B", cat: "Classic muscle", shape: "muscle", price: 7000, unlock: { crew: "otto" }, blurb: "Otto Brandt's championship car. He kept it under a sheet for twenty years and only sells it to his own driver.",
      acc: 470, drag: 0.665, grip: 5.6, brake: 800, steer: 2.45, mass: 1.4, slide: 0.4, nitro: N(380, 0.42, 0.05, 1.27) },
    bulldozer: { name: "Bulldozer Street Truck", cls: "B", cat: "Street pickup truck", shape: "truck", price: 8800, unlock: { pursuitHeat: 3 }, blurb: "Built by Port Kerbside's tow-truck crews to outrun the police. Sold only to people who already have.",
      acc: 476, drag: 0.67, grip: 6.1, brake: 900, steer: 2.5, mass: 1.65, offroad: 0.45, wet: 0.04, nitro: N(370, 0.42, 0.054, 1.27) },
    vanguard: { name: "Vanguard SC", cls: "A", cat: "Modern muscle", shape: "muscle", price: 14200, unlock: { chapter: 4 }, blurb: "Modern muscle: a supercharged V8, real brakes and a chassis that finally keeps up.",
      acc: 498, drag: 0.652, grip: 6.6, brake: 980, steer: 2.65, mass: 1.35, slide: 0.15, nitro: N(395, 0.4, 0.056, 1.29) },
    volta: { name: "Volta EV", cls: "S", cat: "Electric hypercar", shape: "super", price: 31000, unlock: { flag: "tourney_dragkings" }, blurb: "Four motors, no gears, no noise but a whine. The Drag Kings' prize, and the quickest thing off the line in Port Kerbside.",
      acc: 528, drag: 0.632, grip: 7.4, brake: 1080, steer: 2.85, mass: 1.25, nitro: N(400, 0.36, 0.06, 1.3) },
    vecchia: { name: "Corsa Vecchia '58", cls: "B", cat: "Vintage single-seater", shape: "open", price: 9800, unlock: { flag: "grudge_valentina_won" }, blurb: "Valentina's grandfather raced this in 1958. She'll only sell it to someone who beat her fair.",
      acc: 455, drag: 0.655, grip: 6.6, brake: 900, steer: 2.9, mass: 0.85, slide: 0.3, nitro: N(360, 0.42, 0.055, 1.26) },
  };
  // Each car's identity: how its power arrives (band: −1 all low-down torque … +1 all top-end revs; top speed is
  // unchanged), small stat changes that keep near-twins apart, a one-line handling note, its own body details (art)
  // and its own engine voice. Merged into CARS below.
  const IDENTITY = {
    pacer: { factory: { paint: "#e9c44a" }, band: 0.2, handling: "Featherweight and honest: carries speed through corners, runs out of puff on straights.",
      art: { len: 0.96, add: ["airbox"] }, voice: { cyl: 4, idle: 64, span: 140, rasp: 0.3 } },
    kitsune: { factory: { paint: "#ff4fa3", wheels: "white" }, band: 0.7, handling: "Screams to the redline, darts into hairpins, sulks on long straights.",
      art: { add: ["towhook"] }, voice: { cyl: 3, idle: 74, span: 160, rasp: 0.5 } },
    mistral: { factory: { paint: "#2f7de1", decal: "checker" }, band: -0.2, set: { slide: 0.15 }, handling: "A forgiving rally hatch: grips in the wet, shrugs off the gravel, slides when you ask.",
      art: { len: 0.95, remove: ["spots"], add: ["lightbar"] }, voice: { cyl: 4, idle: 56, span: 118, drive: 0.45 } },
    vela: { factory: { paint: "#d23c3c", wheels: "black" }, band: 0, set: { turbo: 0.1, steer: 2.75, brake: 950 }, handling: "Modern hot hatch: a small turbo, strong brakes, pushes wide if you rush in.",
      art: { add: ["fenderVents"] }, voice: { cyl: 4, idle: 60, span: 126, sc: 0, whoosh: 1 } },
    ronin: { factory: { paint: "#f2f2f2", wheels: "bronze", decal: "bolt" }, band: 0.3, handling: "Rear-drive and loose: the drifters' favourite. Throttle steers it.",
      art: { head: "popup", add: ["louvresRear"] }, voice: { cyl: 6, idle: 52, span: 132, drive: 0.4, rasp: 0.2 } },
    dune: { factory: { paint: "#c7a27c", wheels: "black" }, band: -0.4, set: { grip: 6.6 }, handling: "Long-travel raider: heavy and slow to turn, but gravel barely slows it.",
      art: { len: 1.04, wid: 1.05, add: ["snorkel", "spare"], remove: ["bonnetVents"] }, voice: { cyl: 5, idle: 50, span: 110, drive: 0.5, lope: 0.15 } },
    kestrel: { factory: { paint: "#6b7280", finish: "metallic" }, band: 0, handling: "The honest grand tourer: no tricks, no vices, does everything well.",
      art: { add: ["fenderVents"] }, voice: { cyl: 6, idle: 48, span: 128 } },
    brute: { factory: { paint: "#ffd23a", paint2: "#14161a", decal: "stripe" }, band: -0.8, set: { slide: 0.35 }, handling: "All torque, little grip: launches like a train and the tail steps out on exit.",
      art: { add: ["hoodPins"] }, voice: { cyl: 8, idle: 36, span: 84, lope: 0.45, drive: 0.75 } },
    ardent: { factory: { paint: "#3a3f48", finish: "metallic", wheels: "black" }, band: 0.1, set: { wet: 0.06 }, handling: "Four-wheel-drive sports saloon: the best brakes in its class and sure-footed in the rain.",
      art: { head: "slit", add: ["fenderVents"] }, voice: { cyl: 6, idle: 50, span: 124, rasp: 0.15 } },
    longhaul: { factory: { paint: "#7a1f2b" }, band: -0.2, set: { turbo: 0.15 }, handling: "The sleeper: a big turbo that wakes up late, then pulls like a freight train.",
      art: { remove: ["rails"], add: ["roofBox"] }, voice: { cyl: 5, idle: 46, span: 108, whoosh: 1 } },
    hayate: { factory: { paint: "#1b1d22", wheels: "gold" }, band: 0.7, set: { turbo: 0.12, steer: 2.95, grip: 6.7 }, handling: "High-revving turbo coupe: lazy below half revs, then it flies. Turns in sharply.",
      art: { len: 1.03, head: "slant", add: ["wingFactory", "hoodPins"] }, voice: { cyl: 6, idle: 54, span: 150, rasp: 0.35, whoosh: 1 } },
    lumen: { factory: { paint: "#3cc7d6", wheels: "white" }, band: 0.3, handling: "A light roadster: the sweetest steering in B class, short on power.",
      art: { head: "popup" }, voice: { cyl: 4, idle: 58, span: 136, rasp: 0.25 } },
    stallion: { factory: { paint: "#2f7de1", decal: "stripe" }, band: -0.3, set: { mass: 1.4, slide: 0.15 }, handling: "A heavy muscle car that pulls hardest at speed: a straight-line weapon, a handful in the bends.",
      art: { remove: ["scoop"], add: ["louvresRear", "sidePipes"], head: "round" }, voice: { cyl: 8, idle: 38, span: 92, lope: 0.3, drive: 0.65 } },
    ironclad: { factory: { paint: "#ef7d22", decal: "flame", wheels: "black" }, band: -0.6, set: { mass: 1.5, slide: 0.15 }, handling: "Dex's car: supercharged, heavy as a bus, built to shove. It wins every argument at the door.",
      art: { add: ["pushbar", "hoodPins", "cage"] }, voice: { cyl: 8, idle: 34, span: 88, lope: 0.4, drive: 0.8, sc: 0.025 } },
    tidewater: { factory: { paint: "#1d9a6c", decal: "stripe" }, band: 0.2, handling: "Mara's car: precise, planted and unflappable in the rain. Rewards clean lines.",
      art: { wid: 0.97, head: "slit", remove: ["mudflaps", "spots"], add: ["canards", "towhook"] }, voice: { cyl: 4, idle: 58, span: 130, rasp: 0.2, whoosh: 1 } },
    brickyard: { factory: { paint: "#8a4fd8", decal: "checker", wheels: "gold" }, band: -0.5, set: { mass: 1.2, steer: 2.6, brake: 1020, turbo: 0.06 }, handling: "Benny's car: lazy steering, a heavy nose, huge brakes and torque everywhere. Waits for your mistake.",
      art: { wid: 1.03, head: "quad", remove: ["bulge"], add: ["sidePipes"] }, voice: { cyl: 8, idle: 40, span: 96, lope: 0.2, drive: 0.55 } },
    halcyon: { factory: { paint: "#d23c3c", decal: "hoops" }, band: 0.5, handling: "A track single-seater: featherlight, sharp, unforgiving of a lazy line.",
      art: { len: 1.04, add: ["canards"] }, voice: { cyl: 4, idle: 70, span: 180, rasp: 0.45 } },
    corvid: { factory: { paint: "#1b1d22", paint2: "#d23c3c", decal: "sash" }, band: 0.2, handling: "A prototype: stable at speed, needs commitment to turn in.",
      art: { len: 0.97 }, voice: { cyl: 6, idle: 62, span: 170, rasp: 0.3 } },
    vespera: { factory: { paint: "#f2f2f2", paint2: "#2f7de1", decal: "stripe" }, band: 0, set: { slide: 0 }, handling: "A European GT: stable, superbly braked, a little heavy when you hurry it.",
      art: { len: 1.03, head: "slit", add: ["canards"] }, voice: { cyl: 8, idle: 46, span: 138, drive: 0.4, rasp: 0.25 } },
    tempest: { factory: { paint: "#1f4fa8", paint2: "#e9c44a", decal: "stripe", wheels: "gold" }, band: -0.1, set: { slide: 0.2 }, handling: "The rally icon: four-wheel drive, a turbo, and a car that loves to be thrown sideways on any surface.",
      art: { head: "box", add: ["fenderVents", "cage"] }, voice: { cyl: 4, idle: 54, span: 126, drive: 0.5, whoosh: 1 } },
    goliath: { factory: { paint: "#14161a", decal: "flame" }, band: -0.9, set: { slide: 0.3 }, handling: "A supercharged monster: brutal launch, brutal weight, needs room to stop.",
      art: { len: 1.04, wid: 1.04, remove: ["scoop"], add: ["blower", "sidePipes"] }, voice: { cyl: 8, idle: 32, span: 82, lope: 0.55, drive: 0.85, sc: 0.04 } },
    kaze: { factory: { paint: "#c0c4cc", finish: "metallic" }, band: 0.8, set: { turbo: 0.1 }, handling: "A Japanese supercar: twin turbos, rev-happy, razor-sharp turn-in.",
      art: { head: "slant", remove: ["louvres"], add: ["fenderVents"] }, voice: { cyl: 6, idle: 58, span: 175, rasp: 0.35, whoosh: 1 } },
    summit: { factory: { paint: "#f2f2f2", paint2: "#14161a", decal: "stripe" }, band: 0.4, handling: "Sora's car: the grippiest thing short of a prototype, and it rewards precision.",
      art: { len: 1.05, add: ["canards", "fin"] }, voice: { cyl: 4, idle: 72, span: 190, rasp: 0.5 } },
    sirocco: { factory: { paint: "#7fd44a", finish: "pearl", wheels: "black" }, band: 0, set: { turbo: 0.06 }, handling: "A hybrid hypercar: electric shove off the line, a turbo up top, no gaps in between.",
      art: { len: 1.03, add: ["canards"], remove: ["roofIntake"] }, voice: { cyl: 6, idle: 66, span: 165, whine: 0.05, whoosh: 1 } },
    aurora: { factory: { paint: "#b0122a", finish: "metallic" }, band: -0.2, set: { slide: 0.1 }, handling: "A V12 supercar: torque everywhere, heavy, a little lively at the rear.",
      art: { len: 1.03, add: ["wingFactory"] }, voice: { cyl: 12, idle: 52, span: 160, drive: 0.3, rasp: 0.2 } },
    spectre: { factory: { paint: "#5a2d8a", finish: "metallic", wheels: "black" }, band: 0.4, handling: "The fastest road car in Port Kerbside: wants long straights and brave braking.",
      art: { len: 1.05, wid: 1.03, add: ["canards", "fin"] }, voice: { cyl: 10, idle: 60, span: 185, rasp: 0.4, whoosh: 1 } },
    phantom: { factory: { paint: "#e2ecf5", paint2: "#2f7de1", decal: "sash" }, band: 0.3, handling: "A track prototype: enormous grip and brakes, nervous over kerbs.",
      art: { len: 1.05, wid: 1.03, add: ["canards", "louvres"] }, voice: { cyl: 8, idle: 68, span: 195, rasp: 0.45 } },
    countess: { factory: { paint: "#d23c3c", finish: "pearl", wheels: "gold" }, band: 0.1, set: { wet: 0.06 }, handling: "Valentina's car: balanced to the last gram. Does nothing wrong and forgives nothing.",
      art: { len: 1.05, head: "slant", add: ["fenderVents", "louvresRear"] }, voice: { cyl: 12, idle: 56, span: 170, rasp: 0.3 } },
    interceptor: { band: -0.5, handling: "Port Kerbside Police: heavy, fast, built to shove.",
      art: { add: ["pushbar", "aerial"] }, voice: { cyl: 8, idle: 40, span: 100, lope: 0.25, drive: 0.6 } },
    kurogane: { factory: { paint: "#f2f2f2", paint2: "#d23c3c", decal: "sash", wheels: "bronze" }, band: 0.4, handling: "The loosest car in the game: kick the tail out on entry and steer it on the throttle.",
      art: { wid: 1.03, add: ["wingFactory", "fenderVents", "canards"] }, voice: { cyl: 6, idle: 56, span: 150, rasp: 0.45, whoosh: 1 } },
    tsubame: { factory: { paint: "#ffd23a", paint2: "#14161a", decal: "stripe", wheels: "black" }, band: 0.6, handling: "Huge wing, sticky tyres, a rev-happy turbo: fastest through the corners in A class, needs revs to pull.",
      art: { len: 1.04, add: ["wingFactory", "canards", "fenderVents", "hoodPins"] }, voice: { cyl: 4, idle: 62, span: 172, rasp: 0.55, whoosh: 1 } },
    valkyrie: { factory: { paint: "#ff7a1a", finish: "metallic", wheels: "black" }, band: 0.55, handling: "Mid-engined and balanced: rotates neatly into corners, punishes a clumsy lift.",
      art: { wid: 1.02, add: ["fenderVents"] }, voice: { cyl: 10, idle: 58, span: 180, rasp: 0.35 } },
    montecarlo: { factory: { paint: "#14325c", finish: "metallic", wheels: "gold" }, band: -0.55, handling: "A V12 grand tourer: effortless torque, heavy in the bends, unstoppable on the straights.",
      art: { len: 1.06, head: "slant", add: ["louvresRear"] }, voice: { cyl: 12, idle: 50, span: 150, drive: 0.3 } },
    feather: { factory: { paint: "#e8e8e8", paint2: "#1d9a6c", decal: "stripe", wheels: "gold" }, band: 0.5, handling: "The lightest car in the game: sublime grip and steering, and you'll be overtaken on every straight.",
      art: { len: 0.95, add: ["canards"] }, voice: { cyl: 4, idle: 66, span: 160, rasp: 0.4 } },
    thunderbolt: { factory: { paint: "#1f6b4a", decal: "stripe", wheels: "steel" }, band: -0.9, handling: "1969 muscle: a mountain of torque, drum brakes and a tail that wants to lead. Brake early, exit smoking.",
      art: { head: "round", remove: ["scoop"], add: ["chrome", "hoodPins"] }, voice: { cyl: 8, idle: 33, span: 80, lope: 0.6, drive: 0.8 } },
    bulldozer: { factory: { paint: "#9a1b1b", wheels: "black" }, band: -0.7, handling: "The heaviest car in the game: shoves anything out of its way, shrugs off gravel, needs a long run at a corner.",
      art: { add: ["pushbar"] }, voice: { cyl: 8, idle: 36, span: 86, lope: 0.35, drive: 0.7, sc: 0.02 } },
    vanguard: { factory: { paint: "#3a3f48", paint2: "#d23c3c", decal: "stripe", finish: "metallic" }, band: -0.4, handling: "Modern muscle: a supercharged shove with brakes and a chassis that can finally use it.",
      art: { len: 1.03, head: "slit", remove: ["scoop"], add: ["fenderVents", "louvresRear", "hoodPins"] }, voice: { cyl: 8, idle: 38, span: 98, lope: 0.25, drive: 0.65, sc: 0.03 } },
    volta: { factory: { paint: "#e2ecf5", paint2: "#38e8ff", decal: "stripe", finish: "pearl" }, band: -1, handling: "Electric: every bit of torque from a standstill, no gears, no turbo lag. Fades a little at the very top.",
      art: { len: 1.04, add: ["canards"], remove: ["louvres", "intakes"] }, voice: { cyl: 0, electric: true, idle: 90, span: 260 } },
    vecchia: { factory: { paint: "#b0122a", wheels: "steel" }, band: -0.2, handling: "A 1958 racer: skinny tyres, no wings, a straight-eight. It drifts through every corner whether you want it to or not.",
      art: { len: 0.97, remove: ["wings", "airbox"], add: ["headrest"] }, voice: { cyl: 8, idle: 52, span: 130, rasp: 0.55, drive: 0.4 } },
  };
  for (const [id, x] of Object.entries(IDENTITY)) { const c = CARS[id]; Object.assign(c, x.set || {}); c.band = x.band; c.handling = x.handling; c.art = x.art || {}; c.voice = x.voice || {}; c.factory = x.factory || null; }
  const CLASS_COST = { C: 1, B: 1.45, A: 2.05, S: 2.9 };

  // Upgrades: three levels each. Effects are applied in KerbsideCareer.carStats() and tested.
  const UPGRADES = {
    engine: { name: "Engine", per: "+4% acceleration and top speed", cost: [450, 1000, 1900] },
    turbo: { name: "Turbo", per: "+5% power once it spools up (about half a second)", cost: [600, 1300, 2400] },
    ecu: { name: "ECU tune", per: "+2% acceleration and top speed", cost: [250, 550, 1000] },
    tires: { name: "Tyres", per: "+5% grip", cost: [350, 800, 1500] },
    brakes: { name: "Brakes", per: "+9% braking", cost: [300, 650, 1200] },
    suspension: { name: "Suspension", per: "+3% grip, +4% steering", cost: [350, 750, 1400] },
    weight: { name: "Weight reduction", per: "−5% weight, +1.5% acceleration, +3% braking", cost: [400, 900, 1700] },
    aero: { name: "Aero kit", per: "more grip at speed, a little more drag", cost: [350, 800, 1500] },
    nitro: { name: "Nitro", per: "+12% refill, +6% boost", cost: [400, 900, 1700] },
  };
  // The parts AI drivers use (they don't tune), so the field stays as it was balanced.
  const AI_PARTS = ["engine", "tires", "brakes", "suspension", "nitro"];
  // Tuning: free to change in the garage. gearing −1 (short: punchier) … +1 (tall: faster at the top); aero 0–1
  // (downforce: grip at speed, a little drag); diff 0–1 (0 grip, 1 loose: slides more for drifting).
  const TYRES = { sport: { name: "Sport", dry: 1, wet: 1 }, soft: { name: "Soft", dry: 1.06, wet: 0.95 }, hard: { name: "Hard", dry: 0.96, wet: 0.98 }, rain: { name: "Rain", dry: 0.94, wet: 1.16 } };
  const PRESETS = {
    balanced: { name: "Balanced", gearing: 0, aero: 0.3, diff: 0.2, tyre: "sport" },
    grip: { name: "Grip", gearing: -0.2, aero: 0.8, diff: 0, tyre: "soft" },
    drift: { name: "Drift", gearing: -0.4, aero: 0, diff: 1, tyre: "hard" },
    sprint: { name: "Sprint", gearing: -0.8, aero: 0.3, diff: 0.2, tyre: "soft" },
    drag: { name: "Drag", gearing: 0.7, aero: 0, diff: 0, tyre: "soft" },
    wet: { name: "Wet", gearing: 0, aero: 0.6, diff: 0.1, tyre: "rain" },
  };
  // Looks: paint and numbers are free; the rest is bought once per car.
  const LOOKS = {
    paint: ["#e9c44a", "#d23c3c", "#2f7de1", "#f2f2f2", "#1d9a6c", "#ef7d22", "#8a4fd8", "#1b1d22", "#3cc7d6", "#c7a27c", "#ff4fa3", "#7fd44a", "#6b7280", "#7a1f2b"],
    decal: { none: { name: "None", price: 0 }, stripe: { name: "Twin stripe", price: 150 }, flame: { name: "Flames", price: 300 },
      checker: { name: "Chequer", price: 250 }, bolt: { name: "Bolt", price: 250 }, hoops: { name: "Hoops", price: 200 }, sash: { name: "Sash", price: 220 },
      laurel: { name: "Champion's laurel", price: 0, earn: "story" } },
    wheels: { steel: { name: "Steel", price: 0, color: "#9aa0a6" }, gold: { name: "Gold mesh", price: 250, color: "#d9b45f" },
      black: { name: "Black split", price: 200, color: "#2b2d31" }, white: { name: "White spoke", price: 200, color: "#e8e8e8" }, bronze: { name: "Bronze five-spoke", price: 260, color: "#a8743a" }, chrome: { name: "Chrome", price: 0, color: "#eef1f5", earn: "collector" } },
    body: { stock: { name: "Stock", price: 0 }, wide: { name: "Wide arches", price: 600 } },
    spoiler: { none: { name: "None", price: 0 }, low: { name: "Lip", price: 200 }, high: { name: "High wing", price: 500 }, duck: { name: "Ducktail", price: 300 } },
    finish: { gloss: { name: "Gloss", price: 0 }, metallic: { name: "Metallic", price: 400 }, matte: { name: "Matte", price: 350 }, pearl: { name: "Pearl", price: 500 }, chrome: { name: "Mirror chrome", price: 0, earn: "champion" } },
    tint: { clear: { name: "Clear", price: 0, color: "#1a2838" }, dark: { name: "Dark", price: 120, color: "#05070a" }, smoke: { name: "Smoke blue", price: 150, color: "#0d1a2e" } },
    lights: { white: { name: "White", price: 0, color: "#fff6d6" }, amber: { name: "Amber", price: 120, color: "#ffd27a" }, ice: { name: "Ice blue", price: 160, color: "#cfe8ff" } },
    exhaust: { single: { name: "Single", price: 0 }, dual: { name: "Dual", price: 150 }, quad: { name: "Quad", price: 300 } },
    numpos: { bonnet: { name: "On the bonnet", price: 0 }, roof: { name: "On the roof", price: 0 }, none: { name: "No number", price: 0 } },
    // body parts (looks only); fits: the body styles each part can be fitted to
    bumper: { stock: { name: "Stock", price: 0 }, lip: { name: "Splitter lip", price: 220, fits: ["kei", "hatch", "rally", "coupe", "roadster", "sedan", "wagon", "muscle", "gt", "super", "truck"] },
      pushbar: { name: "Push bar", price: 260, fits: ["kei", "hatch", "rally", "sedan", "wagon", "muscle", "truck"] }, canards: { name: "Canards", price: 300, fits: ["coupe", "gt", "super", "proto", "open", "rally"] } },
    bonnet: { stock: { name: "Stock", price: 0 }, vented: { name: "Vented", price: 200, fits: ["kei", "hatch", "rally", "coupe", "roadster", "sedan", "wagon", "muscle", "gt", "truck"] },
      carbon: { name: "Carbon", price: 380, fits: ["kei", "hatch", "rally", "coupe", "roadster", "sedan", "wagon", "muscle", "gt", "super", "proto"] },
      scoop: { name: "Scoop", price: 300, fits: ["hatch", "rally", "coupe", "sedan", "wagon", "gt", "truck"] }, pins: { name: "Bonnet pins", price: 90, fits: ["kei", "hatch", "rally", "coupe", "roadster", "sedan", "wagon", "muscle", "gt"] } },
    tyres: { road: { name: "Road tyres", price: 0 }, lettered: { name: "Raised white letters", price: 180 }, offroad: { name: "Chunky off-road tread", price: 220, fits: ["kei", "hatch", "rally", "wagon", "muscle", "truck"] },
      slick: { name: "Shaved slick look", price: 160, fits: ["open", "proto", "super", "gt", "coupe", "roadster", "hatch"] } },
  };
  const LOOK_KEYS = ["decal", "wheels", "body", "spoiler", "finish", "tint", "lights", "exhaust", "numpos", "bumper", "bonnet", "tyres"];

  // ---------------------------------------------------------------- People
  // personality drives racer.js AI: aggressive, defensive, technical, opportunistic, balanced, beginner.
  const DRIVERS = {
    pip: { name: "Pip Hollis", code: "PIP", color: "#3cc7d6", num: 31, personality: "beginner", skill: 0.86, car: "pacer", lvl: 0,
      crew: "Independent", bio: "Another rookie with a borrowed car and a lot of enthusiasm. Brakes early, waves a lot." },
    otto: { name: "Otto Brandt", code: "OTT", color: "#c7a27c", num: 9, personality: "balanced", skill: 0.93, car: "kestrel", lvl: 1,
      crew: "Retired champion", bio: "Won the league twice, twenty years ago. Still races Fridays to keep the kids honest." },
    dex: { name: "Dex Varga", code: "DEX", color: "#ef7d22", num: 66, personality: "aggressive", skill: 0.94, car: "brute", signature: "ironclad", sigTier: 3, lvl: 0,
      crew: "Ironclad", bio: "Ironclad's loudest driver. Fast, fearless, allergic to being passed." },
    mara: { name: "Mara Quill", code: "MAR", color: "#1d9a6c", num: 12, personality: "defensive", skill: 0.95, car: "mistral", signature: "tidewater", sigTier: 3, lvl: 2,
      crew: "Tidewater", bio: "Tidewater's captain. Nobody gets past her on the harbour; she sees you coming." },
    benny: { name: "Benny “Bricks” Kale", code: "BEN", color: "#8a4fd8", num: 3, personality: "opportunistic", skill: 0.955, car: "ardent", signature: "brickyard", sigTier: 3, lvl: 2,
      crew: "The Brickyard", bio: "Runs Old Town's night races and every bet on them. Waits for your mistake." },
    sora: { name: "Sora Lind", code: "SOR", color: "#f2f2f2", num: 5, personality: "technical", skill: 0.975, car: "halcyon", signature: "summit", sigTier: 4, lvl: 2,
      crew: "Summit Works", bio: "Engineer-driver from the ridge. Treats every corner like an equation and usually solves it." },
    valentina: { name: "Valentina Corsa", code: "VAL", color: "#d23c3c", num: 1, personality: "technical", skill: 0.99, car: "countess", lvl: 2,
      crew: "Scuderia Corsa", bio: "“The Countess.” Three-time league champion. Polite, precise, merciless." },
    rook: { name: "Rook", code: "RK", color: "#2b2d31", num: 13, personality: "aggressive", skill: 0.955, car: "stallion", signature: "vanguard", sigTier: 4, lvl: 1,
      crew: "Harlan Holdings", bio: "Banned from the League twice, hired by Victor Harlan for the jobs that need a car and no conscience." },
    jarvis: { name: "JARVIS", code: "JRV", color: "#d23c3c", num: 1, personality: "balanced", skill: 0.985, car: "kestrel", lvl: 1,
      crew: "Quick race", bio: "Your assistant, driving for fun in Quick Race." },
    bleu: { name: "Bleu", code: "BLU", color: "#2f7de1", num: 4, personality: "opportunistic", skill: 0.965, car: "lumen", lvl: 1, crew: "Quick race", bio: "" },
    whitlock: { name: "Whitlock", code: "WIT", color: "#f2f2f2", num: 22, personality: "defensive", skill: 0.94, car: "longhaul", lvl: 1, crew: "Quick race", bio: "" },
  };
  // Who speaks in the story (portraits are drawn from these colours and initials).
  // How each speaker is drawn in the story (skin, hair, hair style, jacket, one detail): see portraitOf() in racer-ui.js.
  const FACES = {
    jarvis: { skin: "#a8ecff", hair: "#3a8fb0", style: "visor", jacket: "#16343f", extra: "glow" },
    nia: { skin: "#7a4a2e", hair: "#1a120c", style: "puff", jacket: "#ef9f4a", extra: "wrench" },
    mags: { skin: "#e3b38c", hair: "#c9c2b4", style: "bob", jacket: "#2c2a26", extra: "headset" },
    ines: { skin: "#d9a07a", hair: "#4a2a1a", style: "long", jacket: "#1d9a6c", extra: "" },
    lio: { skin: "#c68863", hair: "#1d1612", style: "curly", jacket: "#7fd44a", extra: "cap" },
    priya: { skin: "#9a5e3e", hair: "#120c0a", style: "bun", jacket: "#ff8ad1", extra: "glasses" },
    theo: { skin: "#f0c9a4", hair: "#d9b45f", style: "slick", jacket: "#1f6fd6", extra: "" },
    pip: { skin: "#f2c6a0", hair: "#d8642a", style: "messy", jacket: "#3cc7d6", extra: "" },
    otto: { skin: "#e8b896", hair: "#e6e2da", style: "bald", jacket: "#c7a27c", extra: "moustache" },
    dex: { skin: "#b9764e", hair: "#1a1410", style: "buzz", jacket: "#ef7d22", extra: "scar" },
    mara: { skin: "#d9a582", hair: "#0f2e2a", style: "braid", jacket: "#1d9a6c", extra: "" },
    benny: { skin: "#e0aa82", hair: "#3a2214", style: "slick", jacket: "#8a4fd8", extra: "chain" },
    sora: { skin: "#efcfae", hair: "#f2f2f2", style: "bob", jacket: "#2a2c31", extra: "glasses" },
    valentina: { skin: "#e8bf9a", hair: "#6a1010", style: "long", jacket: "#d23c3c", extra: "earring" },
    harlan: { skin: "#e6c3a5", hair: "#b8bcc4", style: "slick", jacket: "#1c2433", extra: "glasses" },
    rook: { skin: "#c99b78", hair: "#0e0e10", style: "buzz", jacket: "#2b2d31", extra: "scar" },
  };
  const CAST = {
    you: { name: "{name}", color: "#e9c44a", initials: "YOU", face: { skin: "#c68863", hair: "#2a1d14", style: "short", jacket: "#e9c44a", extra: "helmet" } },
    jarvis: { name: "JARVIS", color: "#a8ecff", initials: "J", role: "Race engineer, on the radio" },
    nia: { name: "Nia Okafor", color: "#ef9f4a", initials: "NO", role: "Mechanic, Okafor Motors" },
    mags: { name: "Mags Delacroix", color: "#d9b45f", initials: "MD", role: "Port Kerbside Racing League" },
    ines: { name: "Ines Halden", color: "#9ad1a0", initials: "IH", role: "Halden Tyres" },
    lio: { name: "Lio Marchetti", color: "#7fd44a", initials: "LM", role: "Scout" },
    priya: { name: "Priya Anand", color: "#ff8ad1", initials: "PA", role: "Sponsor manager" },
    theo: { name: "Theo Marsh", color: "#6fb6ff", initials: "TM", role: "Bluewater Fuel" },
    harlan: { name: "Victor Harlan", color: "#5b6b85", initials: "VH", role: "Harlan Holdings · owner of the League" },
    ...Object.fromEntries(Object.entries(DRIVERS).filter(([k]) => !["jarvis", "bleu", "whitlock"].includes(k))
      .map(([k, d]) => [k, { name: d.name, color: d.color, initials: d.name.split(" ").filter((w) => /^[A-Z]/.test(w)).map((w) => w[0]).join("").slice(0, 2), role: d.crew }])),
  };
  for (const [k, f] of Object.entries(FACES)) if (CAST[k]) CAST[k].face = f;
  // Your crew. perk is what they do for you (applied in racer-career.js); recruit says how they join.
  const CREW = {
    nia: { name: "Nia Okafor", role: "Lead mechanic", perk: "Repairs cost 30% less; she'll fit one free upgrade level when loyalty peaks.", recruit: "With you from day one." },
    otto: { name: "Otto Brandt", role: "Race coach", perk: "+10% XP from every race.", recruit: "Choose him in “Build the Crew”, or win his “Master Class” challenge." },
    pip: { name: "Pip Hollis", role: "Teammate", perk: "Races team events with you and blocks for you in the finale.", recruit: "Choose Pip in “Build the Crew”, or help in “Pip's First Podium”." },
    lio: { name: "Lio Marchetti", role: "Scout", perk: "Finds events early: side events need 30% less reputation; hears rumours first.", recruit: "Pass “The Scout's Test” at Harbourside." },
    priya: { name: "Priya Anand", role: "Sponsor manager", perk: "+10% prize money and one more sponsor contract at a time.", recruit: "Win “The Pitch” in Old Town." },
    dex: { name: "Dex Varga", role: "Specialist driver", perk: "Drives team events; rivals think twice before shoving you.", recruit: "Invite him after “Dex's Last Stand” (if he respects you)." },
  };
  // What rivals say after racing you, chosen from what actually happened between you (racer-career.js rivalReaction).
  const RIVAL_LINES = {
    dex: { dirty: "You hit me {youHit} times out there. Next time I hit back.", cleanWin: "Clean pass. I hate that I respect it.", closeWin: "By a nose. A nose! Again. Now.",
      closeLoss: "Close, rookie. Close only counts in horseshoes.", bullied: "Yeah, I leaned on you. That's racing.", passedMany: "{passedThem} times you came past me. I'm going to have nightmares.", loss: "Ironclad sends its regards.", ally: "Good race, partner." },
    mara: { dirty: "I don't race people who drive like that. Fix it.", cleanWin: "You found a way through. Nobody does that.", closeWin: "Inches. I'll find them next time.",
      closeLoss: "The wall held. Barely.", bullied: "Sorry about the door. You left it open.", passedMany: "You kept coming. {passedThem} passes. Respect.", loss: "Tidewater holds the harbour.", ally: "Harbour's with you." },
    benny: { dirty: "Contact costs extra, superstar. Remember that.", cleanWin: "I've got money on you now. Don't let me down.", closeWin: "That finish would've paid twenty to one.",
      closeLoss: "So close! I almost felt bad taking your money.", bullied: "A little nudge. Business.", passedMany: "You were all over me. {passedThem} times!", loss: "House wins.", ally: "Brickyard's got your back." },
    sora: { dirty: "Contact is a failure of planning. Yours.", cleanWin: "Your line through the long left: wrong, and faster. Again.", closeWin: "{gap} seconds. Statistically we are equal. I don't believe in statistics.",
      closeLoss: "Close. I measured it.", bullied: "I took your line. It was the correct one.", passedMany: "You overtook {passedThem} times. Inefficient, but effective.", loss: "Solved.", ally: "Summit Works will share data with you." },
    valentina: { dirty: "Champions don't need to touch. Learn that.", cleanWin: "Well driven. Truly.", closeWin: "That is the closest anyone has come in three years.",
      closeLoss: "You'll get there. Not today.", bullied: "Forgive me. You were in my way.", passedMany: "You kept passing me. How tiresome. How wonderful.", loss: "Thank you for the race.", ally: "Call me Val." },
  };
  // Endings, chosen in order: the first whose conditions you meet (racer-career.js endingFor).
  const ENDINGS = [
    { id: "legend", title: "Legend of Port Kerbside", needs: "Win the Grand Prix with a loyal crew and two allies among the rivals, and either a championship title or Harlan exposed.",
      lines: ["Every crew in Port Kerbside sends a car to your victory parade.", "Mags renames the Kerbside hairpin after you.", "Valentina asks to drive for Okafor Motors next season."] },
    { id: "people", title: "The People's Champion", needs: "Win having turned Harlan down, sided with the night crews and looked after the people Harlan was squeezing.",
      lines: ["The night crews paint your number on every wall in Old Town.", "Benny runs a youth racing school with your prize money matched.", "The League grumbles. The city doesn't care."] },
    { id: "corporate", title: "The Champion of the League", needs: "Win in Harlan's colours, or on the League route with a sponsor manager on your crew.",
      lines: ["Three sponsors fight over your next contract.", "Your face is on a billboard on the Harbour straight.", "The trophy is Harlan's. The money is yours. Mostly."] },
    { id: "lone", title: "The Lone Wolf", needs: "Win the Grand Prix with two feuds or a crew that doesn't trust you.",
      lines: ["You won. The garage is quiet afterwards.", "Nobody from the old crews comes to the party.", "The trophy looks good on an empty shelf."] },
    { id: "champion", title: "Kerbside Champion", needs: "Win the Kerbside Grand Prix.", lines: [] },
  ];
  const SPONSORS = {
    halden: { name: "Halden Tyres", rep: "ines", bonus: 0.15, blurb: "+15% prize money on every podium." },
    bluewater: { name: "Bluewater Fuel", rep: "theo", bonus: 0.1, nitroFill: 0.08, blurb: "+10% prize money and +8% nitro refill." },
  };

  // Sponsor contracts: a deal for a number of career races; reach the target inside them and it pays (once). Up to
  // three at once. Quick races and free play don't count. Walking away from a contract costs 5 reputation.
  const CONTRACTS = {
    "k-podiums": { sponsor: "Halden Tyres", title: "Podium Push", goal: { type: "podiums", n: 3 }, races: 6, pay: 2500, rep: 10, minRep: 0, blurb: "Three podiums in six races." },
    "k-clean": { sponsor: "Okafor Insurance", title: "Clean Sheet", goal: { type: "clean", n: 3 }, races: 5, pay: 2000, rep: 8, minRep: 0, blurb: "Finish three races against others without touching anyone." },
    "k-wins": { sponsor: "Bluewater Fuel", title: "Winning Habit", goal: { type: "wins", n: 2 }, races: 6, pay: 3500, rep: 15, minRep: 30, blurb: "Win two races in six." },
    "k-drift": { sponsor: "Slipstream Apparel", title: "Sideways Season", goal: { type: "drift", n: 10000 }, races: 4, pay: 3000, rep: 10, minRep: 40, blurb: "10,000 drift points in four races." },
    "k-drag": { sponsor: "Torque Monthly", title: "Quarter-Mile Club", goal: { type: "drag", n: 2 }, races: 5, pay: 3000, rep: 10, minRep: 50, blurb: "Win two drag races in five." },
    "k-escape": { sponsor: "Nightline Radio", title: "Most Wanted", goal: { type: "escapes", n: 2 }, races: 5, pay: 4000, rep: 12, minRep: 60, blurb: "Escape the police twice in five tries." },
    "k-endurance": { sponsor: "Halden Tyres", title: "Long Haul", goal: { type: "endurance", n: 1 }, races: 4, pay: 4500, rep: 15, minRep: 80, blurb: "A podium in an endurance race within four races." },
    "k-elite": { sponsor: "Corsa Group", title: "Elite Series", goal: { type: "wins", n: 4 }, races: 8, pay: 9000, rep: 30, minRep: 250, blurb: "Four wins in eight races." },
  };
  // Team levels: your team's reputation (from wins, podiums, contracts and seasons) moves Okafor Motors up; each
  // level adds a perk on top of the last.
  const TEAM_LEVELS = [
    { rep: 0, name: "Back-street garage", perk: "" },
    { rep: 40, name: "Licensed workshop", perk: "Repairs cost 15% less." },
    { rep: 100, name: "Race team", perk: "+5% prize money in career races." },
    { rep: 200, name: "Works team", perk: "Upgrades cost 10% less." },
    { rep: 350, name: "Factory team", perk: "One more sponsor contract at a time." },
  ];
  // What some achievements pay: money, or an exclusive look (marked earn: in LOOKS).
  const ACH_REWARDS = { first_win: { money: 500, text: "₭500" }, podium10: { money: 1500, text: "₭1,500" }, turf: { money: 2000, text: "₭2,000" }, full_crew: { money: 3000, text: "₭3,000" },
    gold_all: { money: 5000, text: "₭5,000" }, escape_artist: { money: 5000, text: "₭5,000" }, every_ending: { money: 10000, text: "₭10,000" },
    story: { text: "the Champion's laurel decal" }, champion: { text: "the Mirror chrome finish" }, collector: { text: "Chrome wheels" } };
  // Team championship: your team against the four home crews and Scuderia Corsa. A season is ten race days.
  const TEAM_SEASON = 10, SEASON_PRIZE = [8000, 4000, 2000, 0, 0, 0];
  const CREWS = { Ironclad: "dex", Tidewater: "mara", "The Brickyard": "benny", "Summit Works": "sora", "Scuderia Corsa": "valentina" };

  // ---------------------------------------------------------------- World
  const DISTRICTS = {
    park: { name: "Kerbside Park", track: "kerbside", x: 22, y: 64, blurb: "Club racing under the old oaks. Where everyone starts." },
    harbour: { name: "Harbourside", track: "harbour", x: 70, y: 70, blurb: "Long straights by the cranes. Tidewater's turf." },
    oldtown: { name: "Old Town", track: "oldtown", x: 48, y: 36, blurb: "Cobbled corners, canal bridges and Benny's night races." },
    ridge: { name: "The Ridge", track: "ridge", x: 78, y: 22, blurb: "Switchbacks above the city. Summit Works tests here." },
  };
  // Par lap times (seconds) per track for medals: gold ≈ a clean lap in a Class B car (simulated Kestrel, engine 1, +5%).
  const PAR = { kerbside: 18.9, harbour: 12.9, ridge: 19.0, oldtown: 15.4 };

  const L = (who, text, cond) => (cond ? [who, text, cond] : [who, text]);
  // ---------------------------------------------------------------- Story
  // goal: place (max), time (max total seconds), drift (min score), survive (not eliminated, place ≤ max).
  // choice.when: "before" (asked before the race) or "after" (asked after a win). flags set by choices change later
  // lines (cond "flag" or "!flag"), opponents and rewards.
  const CHAPTERS = [
    { id: 1, title: "The Beginning", district: "park", blurb: "An unknown driver, a rebuilt car and one Friday night.",
      missions: [
        { id: "c1-shakedown", title: "Shakedown", track: "kerbside", mode: "timetrial", laps: 2, field: [], time: "day", weather: "dry", tier: 1,
          goal: { type: "time", max: 46 },
          intro: [L("nia", "There she is. The Pacer. Took me a winter and most of my patience."), L("jarvis", "Telemetry's live, {name}. Two clean laps in under forty-six seconds and Nia lets you race."),
            L("nia", "Don't bin it on the first corner. That's all I ask.")],
          win: [L("nia", "Not bad. Not bad at all. Mags runs a club night Fridays. You're in."), L("jarvis", "I've logged your best lap. It'll come back to haunt you as a ghost.")],
          lose: [L("nia", "Smooth is fast. Again."), L("jarvis", "Brake a touch earlier into the hairpin. You're losing more than you gain.")] },
        { id: "c1-clubnight", title: "Club Night", track: "kerbside", mode: "circuit", laps: 3, field: ["pip", "otto", "dex"], time: "dusk", weather: "dry", tier: 1,
          goal: { type: "place", max: 3 },
          intro: [L("mags", "Welcome to the Port Kerbside Racing League, rookie. Three laps, top three gets you a licence."),
            L("dex", "Another one of Nia's projects? Stay out of my mirrors."), L("pip", "Ignore Dex. Hi! I'm Pip. First race too. Good luck!")],
          win: [L("mags", "Licence approved. Don't make me regret it."), L("dex", "Beginner's luck. Next time it's just you and me.")],
          lose: [L("otto", "You're quick in the fast stuff. Learn to wait in the slow stuff."), L("mags", "Come back next week. The licence isn't going anywhere.")] },
        { id: "c1-callout", title: "Dex Calls You Out", track: "kerbside", mode: "rival", laps: 3, field: ["dex"], time: "night", weather: "dry", tier: 1,
          goal: { type: "place", max: 1 },
          scene: { focus: "dex", place: "Ironclad territory · Kerbside Park, after dark" },
          intro: [L("nia", "Orange car, number 66. That's Dex Varga. His dad built half the cars in the Ironclad garage."),
            L("nia", "Dex has spent ten years proving he's more than the boss's son. Mostly by running people off the road."),
            L("dex", "Okafor's little project. I hear you've been telling people the Pacer's quick."),
            L("dex", "One on one. Three laps. Loser buys the Ironclad crew dinner."),
            L("nia", "I rebuilt his first car when he was fifteen. He rolled it in a week and never paid me."),
            L("dex", "You're still on about that? I was a kid, Nia. ...I'll pay you when I've beaten your new driver."),
            L("jarvis", "He brakes late and leaves the door open on the exit. Patience, {name}.")],
          win: [L("dex", "...Fine. You can drive."), L("nia", "And that's the first time anyone's seen him lose at home. He'll remember it."), L("jarvis", "Word travels. Harbourside has heard about you.")],
          lose: [L("dex", "Dinner's at eight. Bring your wallet."), L("nia", "He's all bark on the brakes. Get him on the exit of the hairpin.")],
          choice: { when: "after", prompt: "Dex holds out a hand. Sort of.", options: [
            { label: "Shake it. Good race.", flags: { dex_respect: true }, lines: [L("dex", "Don't get used to it.")], respect: { dex: 2 } },
            { label: "Tell him to watch his mirrors.", flags: { dex_feud: true }, lines: [L("dex", "Oh, it's like that? Good.")], respect: { dex: -2 } }] },
          rewards: { district: "harbour", car: "mistral" } },
      ] },
    { id: 2, title: "Building a Reputation", district: "harbour", blurb: "The harbour crews don't care about club licences.",
      missions: [
        { id: "c2-sprint", title: "Harbour Sprint", track: "harbour", mode: "sprint", laps: 1, field: ["mara", "pip", "otto"], time: "day", weather: "dry", tier: 2,
          goal: { type: "place", max: 2 },
          intro: [L("mags", "One lap, flat out. Harbourside wants to see if the rumours are true."), L("mara", "I'm Mara. Tidewater. I'll be the one in front.")],
          win: [L("mara", "Huh. You can pass. Most can't."), L("jarvis", "Reputation's climbing. Sponsors read the results sheets.")],
          lose: [L("mara", "Close. The harbour's long, but it isn't that long."), L("jarvis", "Save nitro for the last straight. One lap means no second chance.")] },
        { id: "c2-elim", title: "Tidewater Elimination", track: "harbour", mode: "elimination", laps: 3, field: ["mara", "dex", "pip", "otto"], time: "dusk", weather: "dry", tier: 2,
          goal: { type: "survive", max: 2 },
          intro: [L("mags", "Last car at the end of every lap goes home. Simple."), L("dex", "Ironclad's here too. Thought you'd miss me.", "dex_feud"),
            L("dex", "Ironclad's here too. Race clean and I'll race clean.", "dex_respect")],
          win: [L("mara", "Tomorrow. Just us. If you're brave enough."), L("jarvis", "That's an invitation, by harbour standards.")],
          lose: [L("otto", "In an elimination you race the car behind, not the one in front."), L("mags", "Out is out. Try again.")] },
        { id: "c2-wall", title: "Mara's Wall", track: "harbour", mode: "rival", laps: 3, field: ["mara"], time: "night", weather: "rain", tier: 2,
          goal: { type: "place", max: 1 },
          intro: [L("mara", "Rain tonight. Good. It slows people who think too much."), L("jarvis", "She defends the inside line every time. Pass her on the outside, into the chicane.")],
          win: [L("mara", "Okay. I'll tell Old Town you're coming. Benny will want a piece of you."), L("nia", "Old Town's tight. I'll set the car up for it.")],
          lose: [L("mara", "The wall holds."), L("jarvis", "Don't follow her line. Make your own.")],
          rewards: { district: "oldtown", car: "kestrel" } },
      ] },
    { id: 3, title: "The Competition", district: "oldtown", blurb: "Night races, real money and the first sponsors.",
      missions: [
        { id: "c3-brickyard", title: "Brickyard Night", track: "oldtown", mode: "circuit", laps: 3, field: ["benny", "dex", "mara", "pip"], time: "night", weather: "dry", tier: 3,
          goal: { type: "place", max: 3 },
          intro: [L("benny", "Welcome to the Brickyard, superstar. Odds on you are, ah, generous."), L("jarvis", "Benny sits behind and waits. Don't give him a mistake to use.")],
          win: [L("benny", "Well. Now I owe some people money."), L("mags", "Two sponsors called me about you this morning. Pick carefully.")],
          lose: [L("benny", "Thanks for the payout, superstar."), L("jarvis", "Old Town punishes wide lines. Use all the road, but not more.")] },
        { id: "c3-sponsor", title: "Show Them Something", track: "oldtown", mode: "drift", laps: 2, field: [], time: "dusk", weather: "rain", tier: 3,
          goal: { type: "drift", min: 1500 },
          choice: { when: "before", prompt: "Two sponsors want a demonstration. Who do you sign with?", options: [
            { label: "Halden Tyres (+15% prize money on podiums)", flags: { sponsor_halden: true }, sponsor: "halden",
              lines: [L("ines", "Halden. We make the grip; you make it look easy. Show me a slide.")] },
            { label: "Bluewater Fuel (+10% prize money, +8% nitro refill)", flags: { sponsor_bluewater: true }, sponsor: "bluewater",
              lines: [L("theo", "Bluewater. Go big, go loud. Give the cameras some smoke.")] }] },
          intro: [L("jarvis", "Wet cobbles. Hold a slide for points, keep it going for a multiplier. Touch the grass and the combo's gone.")],
          win: [L("ines", "That's a contract.", "sponsor_halden"), L("theo", "The footage is gold. Welcome aboard.", "sponsor_bluewater")],
          lose: [L("jarvis", "More angle, less speed. Let the rear step out and catch it.")] },
        { id: "c3-bet", title: "Benny's Bet", track: "oldtown", mode: "rival", laps: 3, field: ["benny"], time: "night", weather: "fog", tier: 3,
          goal: { type: "place", max: 1 },
          intro: [L("benny", "Double or nothing, superstar. Fog's in, so no one's watching but us."), L("jarvis", "Visibility's poor. Trust the minimap and your braking points.")],
          win: [L("benny", "Fine! Fine. Take the money. And maybe tell people I let you win."), L("nia", "Nobody will believe him.")],
          lose: [L("benny", "Pleasure doing business."), L("jarvis", "He nitros when he's within a car length. Stay further ahead or further behind.")],
          choice: { when: "after", prompt: "Benny's winnings are on the table. Half of it was promised to the Brickyard youth club.", options: [
            { label: "Take it all. A bet's a bet. (+₭1,500)", flags: { benny_paid: true }, money: 1500, respect: { benny: -1 }, loyalty: { nia: -1, lio: -1 }, influence: { oldtown: -10 },
              consequence: "Old Town turns against you (−10% influence), and Benny races you hard from now on.",
              lines: [L("benny", "Cold. I like it. The kids won't."), L("nia", "We needed the money. I know. I still don't like it.")] },
            { label: "Give the club its share. (+₭500)", flags: { benny_kind: true }, money: 500, respect: { benny: 3 }, loyalty: { nia: 1, lio: 1 },
              consequence: "The Brickyard youth club invites you to its charity sprint.",
              lines: [L("benny", "Huh. You're going to be bad for my business, superstar. I mean that kindly."), L("lio", "Word gets around Old Town fast. That one will help us.")] }] } },
        { id: "c3-league", title: "League Round: Kerbside", track: "kerbside", mode: "circuit", laps: 3, field: ["otto", "benny", "mara", "dex", "pip"], time: "dusk", weather: "dry", tier: 3,
          goal: { type: "place", max: 2 },
          intro: [L("mags", "Full grid. League points. The ridge teams are watching."), L("otto", "Back where you started. Show them how much you've learned.")],
          win: [L("mags", "Summit Works asked for your number. That's never happened to a rookie."), L("mags", "And Victor Harlan was in the tower tonight. He bought the League last month. He was watching you, {name}."),
            L("nia", "Harlan. That's the company that took Dad's engine."), L("jarvis", "The ridge roads are open to you.")],
          lose: [L("otto", "Second-best still learns something. Go again.")],
          rewards: { district: "ridge", car: "brute" } },
      ] },
    { id: 4, title: "The Racing Empire", district: "ridge", blurb: "A garage of your own, a crew, and the elite invitationals.",
      missions: [
        { id: "c4-trial", title: "Summit Works Trial", track: "ridge", mode: "timetrial", laps: 3, field: [], time: "day", weather: "dry", tier: 4,
          goal: { type: "time", max: 61 },
          intro: [L("sora", "Three laps in a minute and one second. My time from last spring. Beat it and we'll talk."), L("jarvis", "Sora's sector times are... annoyingly consistent.")],
          win: [L("sora", "Interesting. Your line through the switchbacks is wrong, and faster. I want to study it.")],
          lose: [L("sora", "Close is a number. It is not the number.")] },
        { id: "c4-fog", title: "Fog on the Ridge", track: "ridge", mode: "circuit", laps: 3, field: ["sora", "otto", "dex", "benny"], time: "dawn", weather: "dry", weatherChange: { at: 18, to: "fog" }, tier: 4,
          goal: { type: "place", max: 3 },
          intro: [L("mags", "Ridge invitational. Fog's rolling in. Race is on."), L("dex", "Heard you're a big deal now. Prove it.", "dex_feud"), L("dex", "Good luck up here. Genuinely.", "dex_respect"),
            L("benny", "Brickyard's youth club is selling raffle tickets to fix the roof, superstar. You'd know why.", "benny_paid"),
            L("benny", "The kids painted your number on the club wall. Don't let it go to your head.", "benny_kind"),
            L("dex", "Since the harbour I check my mirrors for you. Happy?", "grudge_dex_won"), L("dex", "Still owe you for the harbour, {name}. Today's a good day to collect.", "grudge_dex_lost")],
          win: [L("nia", "You're going to need a proper crew for what's coming."), L("jarvis", "I can run the data. You need hands in the garage.")],
          lose: [L("sora", "The fog does not care how brave you are.")],
          rewards: { car: "halcyon" } },
        { id: "c4-crew", title: "Build the Crew", track: "ridge", mode: "rival", laps: 3, field: ["sora"], time: "dusk", weather: "dry", tier: 4,
          choice: { when: "before", prompt: "Two people offer to join Okafor Motors. You can afford one.", options: [
            { label: "Otto Brandt, as your coach (free tyre upgrade)", flags: { crew_otto: true }, grant: { upgrade: "tires" },
              lines: [L("otto", "I'll teach you the tricks I learned the hard way. Starting with tyres.")] },
            { label: "Pip Hollis, as your teammate (Pip races the finale with you)", flags: { crew_pip: true },
              lines: [L("pip", "Really?! I'll block for you. I'll learn to block. I'll learn fast!")] }] },
          goal: { type: "place", max: 1 },
          intro: [L("sora", "Head to head. Show me that line again."), L("jarvis", "She's quickest through the long left. Out-brake her into the switchback after it.")],
          win: [L("sora", "Summit Works will build you a car part, any part. Consider it professional respect.")],
          lose: [L("sora", "Again tomorrow. I am free at six.")] },
        { id: "c4-invitational", title: "Elite Invitational", track: "harbour", mode: "elimination", laps: 4, field: ["sora", "mara", "dex", "benny", "otto"], time: "night", weather: "rain", tier: 4,
          goal: { type: "survive", max: 2 },
          choice: { when: "before", prompt: "Two roads to the championship. Mags wants you in the League's elite programme; Benny says the real racing is underground.", options: [
            { label: "The League route: sponsors, rules, the tower's respect", flags: { route_league: true }, respect: { valentina: 1 }, loyalty: { priya: 1 },
              consequence: "You race Harlan's League: the qualifier runs under his stewards in Old Town, and the underground crews stop calling.",
              lines: [L("mags", "Good. The League looks after its own. Mostly."), L("harlan", "A sensible choice, {name}. The League rewards sensible people.")] },
            { label: "The underground route: night races, crews, no rules", flags: { route_underground: true }, respect: { benny: 2, dex: 1 }, loyalty: { lio: 1, priya: -1 },
              consequence: "You race with the night crews: Harlan's crackdown chases your qualifier to the docks, and Rook comes looking for you.",
              lines: [L("benny", "Welcome to the real Port Kerbside. The Night Series is open to you, starting now."), L("harlan", "The underground. How romantic. I'll see you at the docks.")] }] },
          intro: [L("mags", "Six of the best. Rain. One car out each lap. The champion is watching from the tower."),
            L("valentina", "So this is the rookie. Show me something worth my attention.")],
          win: [L("valentina", "Very well. See you at the championship."), L("mags", "That's your invitation. The Kerbside Grand Prix.")],
          lose: [L("valentina", "Pity."), L("jarvis", "Last car out each lap. Watch the car behind you, not her.")],
          rewards: { car: "corvid" } },
      ] },
    { id: 5, title: "The Championship", district: "park", blurb: "Everything comes back to Kerbside.",
      missions: [
        { id: "c5-qualifier", title: "Qualifier: Old Town", track: "oldtown", mode: "circuit", laps: 3, field: ["valentina", "sora", "dex", "mara", "benny"], time: "night", weather: "rain", tier: 5,
          alt: [{ if: "route_underground", title: "Qualifier: The Docks", track: "harbour", field: ["valentina", "rook", "dex", "mara", "benny"], weather: "fog" }],
          goal: { type: "place", max: 3 },
          intro: [L("mags", "Top three qualify for the Grand Prix. No second chances this week.", "!route_underground"),
            L("lio", "Underground qualifier, at the docks. Harlan's had the police close every road but this one. Rook's on the grid.", "route_underground"),
            L("harlan", "My stewards will be watching very closely, {name}. Very closely.", "route_league"), L("benny", "Odds on you are... honestly, I've stopped taking bets.", "!benny_paid"),
            L("benny", "No hard feelings? No. Hard feelings. I'm coming for you today, superstar.", "benny_paid")],
          win: [L("jarvis", "Qualified. Dex is asking for you, {name}.")],
          lose: [L("nia", "Car's fine. You're fine. Again.")],
          rewards: { car: "sirocco" } },
        { id: "c5-dex", title: "Dex's Last Stand", track: "kerbside", mode: "rival", laps: 3, field: ["dex"], time: "night", weather: "dry", tier: 5,
          goal: { type: "place", max: 1 },
          intro: [L("dex", "Ironclad's sponsor walked. Said I'm yesterday's news. One more race, you and me. Where it started.", "dex_respect"),
            L("dex", "Ironclad's sponsor walked because of you. One more race. No rules.", "dex_feud"),
            L("jarvis", "He'll be more aggressive than ever. Let him make the mistake.", "dex_feud"),
            L("jarvis", "He wants a clean fight. Give him one.", "dex_respect"),
            L("dex", "And it wasn't the sponsor's idea. Harlan bought Ironclad's debt and pulled the money. I'm a line in his spreadsheet.", "!dex_free"),
            L("dex", "No Ironclad, no Harlan, no contract. Just me. Feels lighter than I thought.", "dex_free")],
          win: [L("dex", "Go win the whole thing. Do it for the club.", "dex_respect"), L("dex", "...Fine. You earned it. Don't tell anyone I said that.", "dex_feud")],
          lose: [L("dex", "Still got it."), L("jarvis", "He leaves the door open on exit. You know this.")],
          choice: { when: "after", prompt: "Ironclad is finished. Dex has nowhere to race.", options: [
            { label: "Ask Dex to drive for your team", crew: "dex", needRespect: { dex: 0 }, flags: { dex_asked: true },
              lines: [L("dex", "You'd have me? After everything? ...Yeah. Yeah, I'm in.", "!dex_feud"), L("dex", "You're joking. You'd actually... fine. One season. Don't make it weird.", "dex_feud")],
              refused: [L("dex", "Drive for you? I'd rather walk. Ask me again when you've earned it.")] },
            { label: "Shake hands and let him go", flags: { dex_parted: true }, lines: [L("dex", "See you around, champ. Probably in your mirrors.")] }] } },
        { id: "c5-countess", title: "The Countess", track: "ridge", mode: "rival", laps: 3, field: ["valentina"], time: "dusk", weather: "dry", tier: 5,
          goal: { type: "place", max: 1 },
          intro: [L("valentina", "Before the Grand Prix, a private race. I like to know my opponents."), L("jarvis", "She has no weakness I can find. Maybe the last switchback. Maybe.")],
          win: [L("valentina", "Remarkable. Then the Grand Prix will be worth winning."), L("nia", "She's rattled. I've never seen her rattled.")],
          lose: [L("valentina", "You'll be faster on Sunday. You'll have to be.")] },
        { id: "c5-finale", title: "The Kerbside Grand Prix", track: "kerbside", mode: "circuit", laps: 4, field: ["valentina", "sora", "dex", "mara", "benny"], time: "night", weather: "dry", weatherChange: { at: 28, to: "rain" }, tier: 5,
          goal: { type: "place", max: 1 },
          intro: [L("mags", "The Kerbside Grand Prix. Four laps, night, and rain is on the radar. The whole city is here."), L("pip", "I'm right behind you. Nobody gets past me. Probably.", "crew_pip"),
            L("otto", "Tyres are perfect. Trust them in the wet.", "crew_otto"), L("valentina", "Good luck, {name}. I mean it."),
            L("harlan", "My colours suit you, {name}. Win this and Port Kerbside is ours.", "harlan_signed"), L("nia", "Just drive. We'll talk after.", "harlan_signed"),
            L("rook", "Mr Harlan sends his regards. And me.", "harlan_refused"),
            L("mags", "A word before the start: the Grand Prix stewards have been replaced overnight. Victor Harlan is... unavailable for comment.", "harlan_exposed"),
            L("dex", "Harlan's paint. My driving. Sorry, {name}. Family's family.", "dex_signed"),
            L("jarvis", "Whatever happens, this has been the best data I've ever logged.")],
          win: [L("mags", "Ladies and gentlemen, your new champion of the Kerbside Grand Prix!"), L("valentina", "Keep the car. The Contessa should belong to the champion."),
            L("dex", "From club night to champion. Ironclad drinks are on me.", "dex_respect"), L("dex", "Fine. FINE. You're the best. Happy?", "dex_feud"),
            L("nia", "Okafor Motors, champions. Say it again. I want to hear it again."),
            L("harlan", "Champion of Harlan Holdings. The contract renews automatically. Read the small print.", "harlan_signed"),
            L("harlan", "...Enjoy it. I own the circuit you just won on.", "harlan_refused"),
            L("nia", "And Dad's engine took the flag. He'd have cried. I'm crying.", "nia_engine"),
            L("jarvis", "Logged. Champion, {name}. Free roam is yours: every district, every event.")],
          lose: [L("valentina", "Next year. I'll be waiting."), L("jarvis", "Go again, {name}. The grid will be here.")],
          rewards: { car: "countess", ending: true } },
      ] },
  ];

  // Side events per district: repeatable, discovered as reputation grows. tier sets rewards and AI strength.
  const SIDE = [
    { id: "s-park-tt", district: "park", title: "Park Time Trial", track: "kerbside", mode: "timetrial", laps: 3, field: [], tier: 1, rep: 0 },
    { id: "s-park-drift", district: "park", title: "Oak Avenue Drift", track: "kerbside", mode: "drift", laps: 2, field: [], tier: 1, rep: 20, weather: "rain", goal: { type: "drift", min: 2500 } },
    { id: "s-park-sprint", district: "park", title: "Club Sprint", track: "kerbside", mode: "sprint", laps: 1, field: ["pip", "otto", "dex"], tier: 1, rep: 10 },
    { id: "s-harb-tt", district: "harbour", title: "Pier Time Trial", track: "harbour", mode: "timetrial", laps: 3, field: [], tier: 2, rep: 30 },
    { id: "s-harb-elim", district: "harbour", title: "Crane Yard Elimination", track: "harbour", mode: "elimination", laps: 4, field: ["mara", "dex", "pip", "otto", "benny"], tier: 2, rep: 50, time: "night" },
    { id: "s-harb-drift", district: "harbour", title: "Dockside Drift", track: "harbour", mode: "drift", laps: 2, field: [], tier: 2, rep: 60, goal: { type: "drift", min: 3000 } },
    { id: "s-old-sprint", district: "oldtown", title: "Canal Sprint", track: "oldtown", mode: "sprint", laps: 1, field: ["benny", "mara", "dex"], tier: 3, rep: 80, time: "dusk" },
    { id: "s-old-drift", district: "oldtown", title: "Cobblestone Drift", track: "oldtown", mode: "drift", laps: 2, field: [], tier: 3, rep: 90, weather: "rain", time: "night", goal: { type: "drift", min: 3500 } },
    { id: "s-old-night", district: "oldtown", title: "Midnight Circuit", track: "oldtown", mode: "circuit", laps: 3, field: ["benny", "dex", "mara", "otto", "pip"], tier: 3, rep: 110, time: "night" },
    { id: "s-ridge-tt", district: "ridge", title: "Ridge Time Trial", track: "ridge", mode: "timetrial", laps: 3, field: [], tier: 4, rep: 130 },
    { id: "s-ridge-drift", district: "ridge", title: "Switchback Drift", track: "ridge", mode: "drift", laps: 2, field: [], tier: 4, rep: 150, goal: { type: "drift", min: 4000 } },
    { id: "s-crew-lio", district: "harbour", title: "The Scout's Test", track: "harbour", mode: "timetrial", laps: 2, field: [], tier: 2, rep: 30, crew: "lio", goal: { type: "time", max: 30 } },
    { id: "s-crew-priya", district: "oldtown", title: "The Pitch", track: "oldtown", mode: "circuit", laps: 3, field: ["benny", "mara", "otto"], tier: 3, rep: 90, crew: "priya", goal: { type: "place", max: 1 }, time: "dusk" },
    { id: "s-crew-otto", district: "ridge", title: "Otto's Master Class", track: "ridge", mode: "timetrial", laps: 3, field: [], tier: 4, rep: 130, crew: "otto", goal: { type: "time", max: 60 } },
    { id: "s-crew-pip", district: "park", title: "Pip's First Podium", track: "kerbside", mode: "circuit", laps: 3, field: ["pip", "otto", "dex"], tier: 2, rep: 50, crew: "pip", goal: { type: "place", max: 2 } },
    { id: "s-ridge-sprint", district: "ridge", title: "Summit Sprint", track: "ridge", mode: "sprint", laps: 1, field: ["sora", "otto", "benny", "dex"], tier: 4, rep: 170, weather: "fog" },
    // the newer modes
    { id: "s-park-deliv", district: "park", title: "Parcel Run", track: "kerbside", mode: "delivery", stops: 4, laps: 1, field: [], tier: 1, rep: 5, goal: { type: "delivery", cargo: 0.5 } },
    { id: "s-park-class", district: "park", title: "C-Class Showdown", track: "kerbside", mode: "circuit", laps: 3, cls: "C", field: ["dex", "otto", "pip", "mara"], tier: 1, rep: 15, goal: { type: "place", max: 1 } },
    { id: "s-park-touge", district: "park", title: "Oak Avenue Duel", track: "kerbside", mode: "touge", laps: 1, field: ["dex"], tier: 2, rep: 25, goal: { type: "place", max: 1 }, time: "dusk" },
    { id: "s-harb-drag", district: "harbour", title: "Waterfront Quarter Mile", track: "harbour", mode: "drag", laps: 1, field: ["dex"], tier: 2, rep: 35, goal: { type: "place", max: 1 }, time: "night" },
    { id: "s-harb-endur", district: "harbour", title: "Harbour Enduro", track: "harbour", mode: "endurance", laps: 10, field: ["mara", "otto", "dex", "pip"], tier: 3, rep: 70, goal: { type: "place", max: 3 } },
    { id: "s-old-deliv", district: "oldtown", title: "The Antique Clock", track: "oldtown", mode: "delivery", stops: 5, laps: 1, pace: 285, field: [], tier: 3, rep: 85, time: "dusk", goal: { type: "delivery", cargo: 0.85 } },
    { id: "s-old-drag", district: "oldtown", title: "Brickyard Drag Night", track: "harbour", mode: "drag", laps: 1, field: ["benny"], tier: 3, rep: 95, goal: { type: "place", max: 1 }, time: "night", weather: "rain" },
    { id: "s-old-class", district: "oldtown", title: "B-Class Night Cup", track: "oldtown", mode: "circuit", laps: 3, cls: "B", field: ["benny", "mara", "dex", "otto"], tier: 3, rep: 100, time: "night", goal: { type: "place", max: 2 } },
    { id: "s-ridge-touge", district: "ridge", title: "Summit Touge", track: "ridge", mode: "touge", laps: 1, field: ["sora"], tier: 4, rep: 140, goal: { type: "place", max: 1 }, time: "dawn" },
    { id: "s-old-charity", district: "oldtown", title: "Youth Club Charity Sprint", track: "oldtown", mode: "sprint", laps: 1, field: ["benny", "pip", "mara"], tier: 3, rep: 0, needFlag: "benny_kind",
      time: "dusk", goal: { type: "place", max: 1 }, respectOnWin: { benny: 2 }, blurb: "The kids you helped are racing for a new roof. Benny's driving for them." },
    { id: "s-ridge-endur", district: "ridge", title: "Ridge 12 Laps", track: "ridge", mode: "endurance", laps: 12, field: ["sora", "valentina", "benny", "mara", "otto"], tier: 5, rep: 190, goal: { type: "place", max: 3 }, weatherChange: { at: 90, to: "rain" } },
  ];
  // ---------------------------------------------------------------- Character stories
  // Personal arcs, raced from headquarters between story missions. Each opens when the story reaches it (and, for
  // the crew, when they've joined you). Their turning points set flags that change later missions, the finale and
  // the ending. A mission's alt entries change it when a flag is set (a different track, mode or field).
  const ARCS = {
    nia: { who: "nia", title: "The Okafor Engine", blurb: "Nia's father built engines for half this city. Harlan Holdings took the last one.", open: { chapter: 2 }, missions: [
      { id: "a-nia-1", title: "The Ledger", track: "harbour", mode: "timetrial", laps: 2, field: [], time: "dusk", tier: 2, goal: { type: "time", max: 30 },
        intro: [L("nia", "Found this in Dad's desk. The garage ledger. Every page since 1994."),
          L("nia", "Samuel Okafor built engines for half of Port Kerbside. When he got sick, the bank sold his debt to a company called Harlan Holdings."),
          L("nia", "They took the one thing he never let me touch: the Okafor V8. Said it covered the interest."),
          L("jarvis", "Harlan Holdings owns the repo yard on the harbour. And, since last month, the Racing League."),
          L("nia", "Two quick laps of the harbour. I want to see that yard at speed before we decide anything.")],
        win: [L("nia", "Okay. I know where it is. Next question is how we get it back.")],
        lose: [L("nia", "Again. I'm not walking into Harlan's yard with a driver who can't find the apex.")] },
      { id: "a-nia-2", title: "Lot Seven", track: "harbour", mode: "circuit", laps: 3, field: ["rook", "mara", "otto"], time: "night", tier: 3, goal: { type: "place", max: 1 },
        choice: { when: "before", prompt: "The Okafor V8 sits in Harlan's repo yard as lot seven. How do we get it back?", options: [
          { label: "Take it back tonight. It's ours.", flags: { nia_steal: true }, loyalty: { nia: 1 }, consequence: "A midnight run out of the repo yard. Harlan will know it was you.",
            lines: [L("nia", "Midnight, then. Bring the truck. Don't stop for anything.")] },
          { label: "Win it in the League's auction race.", flags: { nia_buy: true }, consequence: "A clean race for the engine, with Harlan's driver on the grid.",
            lines: [L("nia", "The legal way. Dad would have liked that. I hate it.")] }] },
        alt: [{ if: "nia_steal", title: "Midnight at the Repo Yard", mode: "delivery", stops: 4, pace: 290, field: [], weather: "rain", goal: { type: "delivery", cargo: 0.6 } }],
        intro: [L("harlan", "Lot seven: an Okafor V8, slightly used. Tonight's winner takes it home. Do try, Ms Okafor.", "nia_buy"),
          L("nia", "That's Rook in the black car. Harlan's hired driver. Don't let him lean on you.", "nia_buy"),
          L("nia", "Gate's open for four minutes. Four stops to lose anyone following, then the garage.", "nia_steal"),
          L("jarvis", "The engine's strapped down in the back. Drive smoothly or we're bringing home scrap.", "nia_steal")],
        win: [L("nia", "It's home. Dad's engine is home."), L("harlan", "Ms Okafor. I'll be sending you an invoice. And a lawyer.", "nia_steal"),
          L("harlan", "Well driven. A deal is a deal. I always keep mine. Remember that.", "nia_buy")],
        lose: [L("nia", "Not tonight. It's still there. We go again.")] },
      { id: "a-nia-3", title: "Samuel's Lap", track: "kerbside", mode: "circuit", laps: 3, field: ["dex", "mara", "pip", "otto"], time: "dusk", tier: 3, goal: { type: "place", max: 1 },
        rewards: { upgrade: "engine", money: 1500, loyalty: { nia: 3 }, flags: { nia_engine: true } },
        intro: [L("nia", "It's in. Dad's V8, in your car. He'd have hated the paint."), L("nia", "He used to say an engine remembers who built it. Let's find out."),
          L("otto", "Samuel and I raced each other in '89. He won. Make it sing, kid.")],
        win: [L("nia", "...That's the sound. That's exactly the sound."), L("nia", "Thank you. I mean it. Okafor Motors is yours as much as mine now.")],
        lose: [L("nia", "It's not the engine. It's us. Again.")] }] },

    dex: { who: "dex", title: "Ironclad Blood", blurb: "Harlan bought Ironclad's debt and put his own driver in Dex's seat.", open: { chapter: 3, done: "c1-callout" }, missions: [
      { id: "a-dex-1", title: "Dad's Garage", track: "kerbside", mode: "rival", laps: 3, field: ["rook"], time: "night", tier: 3, goal: { type: "place", max: 1 }, respectOnWin: { dex: 2 },
        intro: [L("dex", "Harlan bought Ironclad's debt. First thing he did: put his own driver in my seat."),
          L("dex", "Rook. Banned from the League twice. Dad thinks he's the future."),
          L("dex", "I can't race him. I'm not even allowed in the garage. You can.", "!dex_feud"),
          L("dex", "I know. I'm the last person you'd help. Do it to annoy Harlan, then.", "dex_feud")],
        win: [L("dex", "Dad watched the whole thing. He didn't say anything. He didn't have to.")],
        lose: [L("dex", "Yeah. That's what Dad saw too.")] },
      { id: "a-dex-2", title: "The Seat", track: "oldtown", mode: "circuit", laps: 3, field: ["rook", "dex", "benny", "mara"], time: "night", tier: 4, goal: { type: "place", max: 2 },
        intro: [L("dex", "Dad says I can have the seat back. If I sign Harlan's contract. One more race to show him what I'm worth.")],
        win: [L("dex", "Two Ironclad cars, both behind you. Dad's going to make me an offer tonight.")],
        lose: [L("dex", "Rook's in front of me again. Great.")],
        choice: { when: "after", prompt: "Dex's father offers him the seat back, if he signs Harlan's contract. Dex asks what you'd do.", options: [
          { label: "Race for yourself, not for Harlan.", flags: { dex_free: true }, respect: { dex: 3 }, consequence: "Dex walks away from Ironclad and Harlan. He'll be easier to bring onto your team.",
            lines: [L("dex", "No contract, no seat, no Harlan. Okay. Okay. I'm going to need a ride.")] },
          { label: "Take the seat. It's your family's garage.", flags: { dex_signed: true }, respect: { dex: 1 }, consequence: "Dex drives Harlan's Ironclad in the Grand Prix.",
            lines: [L("dex", "Yeah. That's what Dad would want. Thanks. I think.")] }] } }] },

    mara: { who: "mara", title: "The Sea Wall", blurb: "Harlan's marina project is bulldozing Tidewater's boathouse.", open: { chapter: 3, done: "c2-wall" }, missions: [
      { id: "a-mara-1", title: "High Tide", track: "harbour", mode: "delivery", stops: 5, laps: 1, field: [], time: "dawn", weather: "rain", tier: 3, goal: { type: "delivery", cargo: 0.8 },
        intro: [L("mara", "Harlan's marina. The bulldozers come Friday. Tidewater's boathouse is in the way."),
          L("mara", "Thirty years of crew records. Trophies. My mother's helmet. Help me move it before the trucks come."),
          L("jarvis", "Five drops along the sea wall. The cargo is irreplaceable. Gently.")],
        win: [L("mara", "Everything's out. Mum's helmet too. I owe you.")], lose: [L("mara", "We'll go again at the next tide. There's still time. Barely.")] },
      { id: "a-mara-2", title: "Last Race at the Boathouse", track: "harbour", mode: "circuit", laps: 3, field: ["mara", "rook", "pip", "otto"], time: "night", tier: 4, goal: { type: "place", max: 2 },
        intro: [L("mara", "One last Tidewater race on our own water. Rook's entered. Harlan wants a picture of him winning it.")],
        win: [L("mara", "No picture for Harlan. Good.")], lose: [L("mara", "He got his picture.")],
        choice: { when: "after", prompt: "Tidewater has nowhere to go. Mara asks if her crew can work out of Okafor Motors.", options: [
          { label: "Yes. There's room. (−₭1,500)", flags: { mara_home: true }, money: -1500, respect: { mara: 3 }, loyalty: { nia: 1 }, influence: { harbour: 15 },
            consequence: "Tidewater moves into your garage: Harbourside backs you (+15% influence) and Mara becomes a close ally.", lines: [L("mara", "Tidewater at Okafor Motors. My mother would laugh.")] },
          { label: "We can't afford it.", flags: { mara_alone: true }, respect: { mara: -1 }, influence: { harbour: -5 }, consequence: "Tidewater scatters, and Harlan's marina goes ahead.",
            lines: [L("mara", "Fair. I'd have said the same. Probably.")] }] } }] },

    benny: { who: "benny", title: "House Rules", blurb: "Harlan bought every marker in Old Town. Including Benny's.", open: { chapter: 4, done: "c3-bet" }, missions: [
      { id: "a-benny-1", title: "Collections", track: "oldtown", mode: "rival", laps: 3, field: ["rook"], time: "night", tier: 4, goal: { type: "place", max: 1 }, respectOnWin: { benny: 2 },
        intro: [L("benny", "Harlan bought my markers. Every debt in Old Town pays his office now."), L("benny", "Rook collects. Tonight he's collecting from me, on the canal road. Race him for it?"),
          L("benny", "And yes, I know. You took the youth club's money. Funny how it comes round.", "benny_paid")],
        win: [L("benny", "Rook went home without his envelope. I could kiss you. I won't.")], lose: [L("benny", "Envelope's gone. So's my watch.")] },
      { id: "a-benny-2", title: "The Brickyard's Last Night", track: "oldtown", mode: "circuit", laps: 3, field: ["benny", "rook", "dex", "mara", "pip"], time: "night", tier: 4, goal: { type: "place", max: 2 },
        intro: [L("benny", "Last night race at the Brickyard, maybe ever. Harlan wants the building for flats.")],
        win: [L("benny", "What a night. What a stupid, perfect night.")], lose: [L("benny", "Not the send-off I wanted.")],
        choice: { when: "after", prompt: "Benny can keep the Brickyard if someone covers his last payment to Harlan.", options: [
          { label: "Pay it. (−₭2,500)", flags: { benny_saved: true }, money: -2500, respect: { benny: 3 }, influence: { oldtown: 10 },
            consequence: "The Brickyard stays open: Old Town backs you (+10% influence) and Benny's on your side for good.", lines: [L("benny", "Nobody's ever paid my debts. I don't know what to do with my face.")] },
          { label: "It's not my debt.", flags: { benny_lost: true }, respect: { benny: -1 }, influence: { oldtown: -5 }, consequence: "Harlan takes the Brickyard. Old Town's night races end.",
            lines: [L("benny", "No. It isn't. See you around, superstar.")] }] } }] },

    sora: { who: "sora", title: "The Equation", blurb: "Summit Works lost its funding. Harlan wants Sora's designs.", open: { chapter: 4, done: "c4-trial" }, missions: [
      { id: "a-sora-1", title: "Data", track: "ridge", mode: "timetrial", laps: 3, field: [], time: "dusk", tier: 4, goal: { type: "time", max: 63 },
        intro: [L("sora", "Summit Works lost its funding. Harlan Holdings has offered to buy my designs. All of them."),
          L("sora", "I'd like to prove they're worth more than his offer. Drive your line through the switchbacks for my sensors.")],
        win: [L("sora", "Seventeen hundredths better than my model. I'll put that in the presentation.")], lose: [L("sora", "The sensors need a cleaner run.")] },
      { id: "a-sora-2", title: "The Pitch", track: "ridge", mode: "touge", laps: 1, field: ["sora"], time: "dawn", tier: 4, goal: { type: "place", max: 1 },
        intro: [L("sora", "The investors are on the summit. One run, you and me. Show them the line is real.")],
        win: [L("sora", "They saw it. Now the question is whose name goes on the data.")], lose: [L("sora", "They saw me win. Not quite the point.")],
        choice: { when: "after", prompt: "Sora can win her funding back if she uses your telemetry, with your name on it.", options: [
          { label: "Share it. Put both our names on it.", flags: { sora_shared: true }, respect: { sora: 3 }, unlockCar: "summit", consequence: "Sora keeps Summit Works and offers you her car early.",
            lines: [L("sora", "Summit Works, with Okafor Motors. It looks right on paper.")] },
          { label: "Keep it. It's our edge.", flags: { sora_kept: true }, respect: { sora: -1 }, consequence: "You keep your advantage, and Sora sells her designs to Harlan.",
            lines: [L("sora", "Understandable. Inefficient, but understandable.")] }] } }] },

    valentina: { who: "valentina", title: "The Countess's Secret", blurb: "Valentina has raced for Harlan's money for three years.", open: { done: "c5-countess" }, missions: [
      { id: "a-val-1", title: "After Hours", track: "kerbside", mode: "rival", laps: 3, field: ["valentina"], time: "night", tier: 5, goal: { type: "place", max: 1 },
        intro: [L("valentina", "I have raced for Harlan's money for three years. I did not know what it bought until last week."),
          L("valentina", "The stewards for the Grand Prix are his. Penalties for whoever he chooses."), L("valentina", "Race me once more, with nobody watching. Then decide if I am worth trusting.")],
        win: [L("valentina", "Good. Then listen.")], lose: [L("valentina", "Not yet, then. Come back when you can beat me.")],
        choice: { when: "after", prompt: "Valentina has the stewards' emails. Going public ends her contract, and maybe her career.", options: [
          { label: "Go public together.", flags: { harlan_exposed: true }, respect: { valentina: 3 }, consequence: "Harlan's stewards are removed before the Grand Prix, and the city learns what he did.",
            lines: [L("valentina", "Together, then. Tomorrow the city will be very loud.")] },
          { label: "Keep it quiet. Win on the track.", flags: { harlan_hidden: true }, consequence: "The Grand Prix runs under Harlan's stewards.",
            lines: [L("valentina", "On the track, then. As it should be. I hope you are right.")] }] } }] },

    harlan: { who: "harlan", title: "The Tower", blurb: "Victor Harlan owns the League, the circuit and most of the city's debts. Now he wants a champion.", open: { done: "c5-qualifier" }, missions: [
      { id: "a-harlan-1", title: "The Exhibition", track: "harbour", mode: "circuit", laps: 3, field: ["rook", "mara", "dex", "sora"], time: "night", tier: 5, goal: { type: "place", max: 3 },
        intro: [L("harlan", "{name}. Victor Harlan. I own the League, this circuit, and most of the debts in this city."),
          L("harlan", "I'd like to own a champion. Race my exhibition tonight. We'll talk after."), L("nia", "Whatever he offers, it's got a hook in it.")],
        win: [L("harlan", "Impressive. Come up to the tower.")], lose: [L("harlan", "Hm. Come up to the tower anyway.")],
        choice: { when: "after", prompt: "Harlan offers ₭10,000 and the Okafor Motors debt cleared, if you race the Grand Prix in Harlan colours.", options: [
          { label: "Sign.", flags: { harlan_signed: true }, money: 10000, loyalty: { nia: -3, lio: -2 }, consequence: "₭10,000 and the debt cleared, but Nia and Lio lose faith in you and the Grand Prix becomes Harlan's show.",
            lines: [L("harlan", "Excellent. Welcome to the future of Port Kerbside."), L("nia", "...I'll be in the garage. Don't follow me.")] },
          { label: "Refuse.", flags: { harlan_refused: true }, loyalty: { nia: 2 }, consequence: "Harlan sends Rook into the Grand Prix to stop you.",
            lines: [L("harlan", "A pity. Then I'll beat you the old-fashioned way. With money."), L("nia", "That's my driver.")] }] } }] },

    otto: { who: "otto", title: "One Last Race", blurb: "Otto's knees are done. He wants one more race, beside you.", open: { chapter: 4, hired: "otto" }, missions: [
      { id: "a-otto-1", title: "One Last Race", track: "ridge", mode: "team", team: true, mate: "otto", laps: 3, field: ["sora", "benny"], time: "dusk", tier: 4, goal: { type: "team" },
        rewards: { loyalty: { otto: 3 }, flags: { otto_last: true } },
        intro: [L("otto", "Doctor says no more racing. My wife says no more racing. So: one more race. You and me, a team, on my ridge."), L("otto", "Don't wait for me. I'll be fine. I'll be slow, but fine.")],
        win: [L("otto", "Thirty years. That's a good last one. Thank you, kid.")], lose: [L("otto", "Not the last one I wanted. Ask me again next week.")] }] },
    pip: { who: "pip", title: "Shaken", blurb: "Pip crashed at the Ridge and hasn't been the same since.", open: { chapter: 4, hired: "pip" }, missions: [
      { id: "a-pip-1", title: "Shaken", track: "kerbside", mode: "touge", laps: 1, field: ["pip"], time: "day", tier: 3, goal: { type: "place", max: 1 }, rewards: { loyalty: { pip: 3 }, flags: { pip_back: true } },
        intro: [L("pip", "Since the crash I brake for corners that aren't there."), L("pip", "Chase me. Push me. If I can't hold you off for one lap, I'll hang up the helmet."), L("nia", "Push him hard. He needs to know he can take it.")],
        win: [L("pip", "You got me. And I didn't flinch once. Not once!"), L("pip", "Again tomorrow. Same time.")], lose: [L("pip", "I held you off! I held YOU off. Okay. Okay, I'm back.")] }] },
    lio: { who: "lio", title: "Old Debts", blurb: "Lio owes money he borrowed from Benny. Harlan owns that marker now.", open: { chapter: 4, hired: "lio" }, missions: [
      { id: "a-lio-1", title: "Old Debts", track: "oldtown", mode: "delivery", stops: 4, laps: 1, field: [], time: "night", tier: 4, goal: { type: "delivery", cargo: 0.5 }, rewards: { loyalty: { lio: 3 }, flags: { lio_clear: true } },
        intro: [L("lio", "Before I scouted for you I borrowed from Benny. Harlan bought the marker. His office closes at midnight."),
          L("lio", "Four stops: the cash is in four envelopes with four of my friends. Then his office. Please hurry.")],
        win: [L("lio", "Paid. Clean. First time in six years I don't owe anyone. Except you.")], lose: [L("lio", "Midnight. Doors locked. Interest doubles. Great.")] }] },
    priya: { who: "priya", title: "Blacklisted", blurb: "Harlan had Priya fired from Bluewater. She has a new sponsor in mind, if you can impress them.", open: { chapter: 4, hired: "priya" }, missions: [
      { id: "a-priya-1", title: "Blacklisted", track: "harbour", mode: "sprint", laps: 1, field: ["mara", "rook", "dex"], time: "dusk", tier: 4, goal: { type: "place", max: 1 }, rewards: { money: 4000, loyalty: { priya: 3 }, flags: { priya_corvo: true } },
        intro: [L("priya", "Bluewater fired me last week. Harlan's board asked them to. I want a sponsor he doesn't own."),
          L("priya", "Corvo Coffee. Small, independent, loud. They're watching this sprint. Win it.")],
        win: [L("priya", "Signed. ₭4,000 up front and they hate Harlan as much as I do.")], lose: [L("priya", "Corvo passed. I'll find another one. I always do.")] }] },
  };
  // The big turning points, for the ending's look back: the flag, and what it says about your career.
  const TURNING_POINTS = [
    ["dex_respect", "You shook Dex's hand on club night."], ["dex_feud", "You told Dex to watch his mirrors."],
    ["benny_paid", "You kept the Brickyard kids' money."], ["benny_kind", "You gave the Brickyard kids their share."],
    ["crew_otto", "You brought Otto in as coach."], ["crew_pip", "You brought Pip in as teammate."],
    ["route_league", "You took the League route."], ["route_underground", "You took the underground route."],
    ["nia_steal", "You stole the Okafor V8 back from Harlan's yard."], ["nia_buy", "You won the Okafor V8 back in Harlan's auction."],
    ["dex_free", "You told Dex to race for himself."], ["dex_signed", "You told Dex to take Harlan's seat."],
    ["mara_home", "You gave Tidewater a home."], ["mara_alone", "You let Tidewater scatter."],
    ["benny_saved", "You paid Benny's last debt."], ["benny_lost", "You let Harlan take the Brickyard."],
    ["sora_shared", "You shared your data with Sora."], ["sora_kept", "You kept your data."],
    ["harlan_exposed", "You and Valentina exposed Harlan's stewards."], ["harlan_hidden", "You kept Harlan's secret and raced anyway."],
    ["harlan_signed", "You signed Harlan's contract."], ["harlan_refused", "You turned Harlan down."],
  ];
  // Grudge matches: after you and a rival have traded paint three times, they call you out, quoting the real count.
  // Win and the grudge is settled your way; lose and they remember. Their later lines change either way.
  const GRUDGE = {
    dex: { track: "harbour", time: "night", offer: "That's {contacts} times we've traded paint, and {youHit} of them were you. Harbour Loop. Midnight. No crews, no excuses.",
      win: [["dex", "...Okay. You don't scare. I'll stop trying to make you."], ["nia", "That's the closest thing to an apology Dex Varga has ever said."]], lose: [["dex", "Now we're even. Mostly."]] },
    mara: { track: "harbour", time: "dawn", offer: "{contacts} contacts, {name}. I don't race people who touch. Settle it on the sea wall at dawn, clean, or don't come near my harbour again.",
      win: [["mara", "Clean. Thank you. You can have the inside line any time."]], lose: [["mara", "That's how it's done. Keep your distance next time."]] },
    benny: { track: "oldtown", time: "night", offer: "You've cost me two mirrors and {contacts} favours. Let's make it official: one race, my canal, my rules.",
      win: [["benny", "I'd call that robbery if I hadn't seen it. Mirrors are on me."]], lose: [["benny", "Pleasure, as always. Send the invoice for the mirrors to yourself."]] },
    sora: { track: "ridge", time: "dusk", offer: "{contacts} contacts is not racing, it's a statistical problem. I would like to solve it. Summit road, tonight.",
      win: [["sora", "Problem solved. Not the way I expected."]], lose: [["sora", "Problem solved."]] },
    valentina: { track: "kerbside", time: "night", offer: "{contacts} times. I am not accustomed to being touched, {name}. One race. Then we will see what you are.",
      win: [["valentina", "Now I see. Very well."]], lose: [["valentina", "As I thought."]] },
  };
  // Rival challenges unlock once you've met the rival in the story (beat them once).
  const RIVAL_CHALLENGES = [
    { id: "r-dex", rival: "dex", after: "c1-callout", district: "park", track: "kerbside", tier: 2 },
    { id: "r-mara", rival: "mara", after: "c2-wall", district: "harbour", track: "harbour", tier: 3 },
    { id: "r-benny", rival: "benny", after: "c3-bet", district: "oldtown", track: "oldtown", tier: 3 },
    { id: "r-sora", rival: "sora", after: "c4-crew", district: "ridge", track: "ridge", tier: 4 },
    { id: "r-valentina", rival: "valentina", after: "c5-countess", district: "ridge", track: "kerbside", tier: 5 },
  ];
  const CHAMPIONSHIPS = [
    { id: "cup", name: "Port Kerbside Cup", after: 2, tier: 2, rounds: [
      { track: "kerbside", time: "day" }, { track: "harbour", time: "dusk" }, { track: "oldtown", time: "day" }, { track: "ridge", time: "day" }],
      field: ["mara", "dex", "otto", "pip", "benny"] },
    { id: "night", name: "Night Series", after: 4, tier: 4, rounds: [
      { track: "oldtown", time: "night" }, { track: "harbour", time: "night", weather: "rain" }, { track: "ridge", time: "night", weather: "fog" }, { track: "kerbside", time: "night" }],
      field: ["sora", "benny", "mara", "dex", "otto"] },
    { id: "masters", name: "Champions' Masters", after: 6, tier: 5, rounds: [
      { track: "ridge", time: "dusk" }, { track: "oldtown", time: "night", weather: "rain" }, { track: "harbour", time: "day" }, { track: "kerbside", time: "night", weather: "rain" }],
      field: ["valentina", "sora", "benny", "mara", "dex"] },
    { id: "storm", name: "Storm Series", after: 3, tier: 3, weatherSeries: true, rounds: [
      { track: "harbour", time: "day", weather: "rain" }, { track: "kerbside", time: "dusk", weather: "dry", weatherChange: { at: 25, to: "rain" } }, { track: "ridge", time: "dawn", weather: "fog" }, { track: "oldtown", time: "night", weather: "rain", weatherChange: { at: 40, to: "dry" } }],
      field: ["mara", "benny", "otto", "dex", "pip"] },
  ];
  // Tournaments: knockout stages in a row. Miss a stage's goal and you're out; win the last for the prize.
  const TOURNAMENTS = [
    { id: "dragkings", name: "Drag Kings", after: 2, tier: 2, prize: 6000, stages: [
      { title: "Round 1", track: "harbour", mode: "drag", field: ["pip"], goal: { type: "place", max: 1 }, time: "night" },
      { title: "Semi-final", track: "harbour", mode: "drag", field: ["dex"], goal: { type: "place", max: 1 }, time: "night" },
      { title: "Final", track: "harbour", mode: "drag", field: ["benny"], goal: { type: "place", max: 1 }, time: "night", weather: "rain" }] },
    { id: "knockout", name: "Kerbside Knockout", after: 3, tier: 4, prize: 12000, stages: [
      { title: "Heat", track: "kerbside", mode: "elimination", laps: 4, field: ["dex", "otto", "pip", "mara", "benny"], goal: { type: "survive", max: 3 } },
      { title: "Semi-final", track: "oldtown", mode: "sprint", laps: 1, field: ["mara", "benny", "dex"], goal: { type: "place", max: 2 }, time: "dusk" },
      { title: "Final", track: "ridge", mode: "touge", laps: 1, field: ["sora"], goal: { type: "place", max: 1 }, time: "night" }] },
  ];
  const POINTS = [10, 7, 5, 3, 2, 1];

  // ---------------------------------------------------------------- Living world
  // Each district has a home crew. Your share of a district grows as you win there; at 75% you run it.
  const TURF = { park: { crew: "Ironclad", rival: "dex" }, harbour: { crew: "Tidewater", rival: "mara" }, oldtown: { crew: "The Brickyard", rival: "benny" }, ridge: { crew: "Summit Works", rival: "sora" } };
  const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  // Crew battles: unlocked when you take over a district; you and your crew driver (2 v 2, points by position)
  // against the home crew.
  const TURF_EVENTS = Object.fromEntries(Object.entries(TURF).map(([d, T]) => [d, { id: "turf-" + d, district: d, title: `Turf War: ${T.crew}`, track: { park: "kerbside", harbour: "harbour", oldtown: "oldtown", ridge: "ridge" }[d],
    mode: "team", laps: 3, team: true, field: [T.rival, ({ park: "otto", harbour: "benny", oldtown: "mara", ridge: "otto" }[d])], tier: 4, goal: { type: "team" }, time: "night" }]));
  // Rumours: heard when you've earned them (a scout hears them sooner); each reveals a secret event with its own reward.
  const RUMORS = [
    { id: "ru-docks", from: "lio", rep: 60, text: "Someone's running unlit races in the container yard after midnight. Invitation only.",
      event: { id: "x-docks", district: "harbour", title: "Container Yard Midnight Run", track: "harbour", mode: "sprint", laps: 1, field: ["mara", "benny", "dex"], tier: 3, time: "night", weather: "fog", goal: { type: "place", max: 1 } },
      reward: { money: 3000, text: "₭3,000 and a set of Tidewater's private paint codes." } },
    { id: "ru-ghost", from: "nia", rep: 120, text: "The old timers say there's a ghost lap on the Ridge: a time from 1987 nobody has beaten.",
      event: { id: "x-ghost", district: "ridge", title: "The 1987 Ghost Lap", track: "ridge", mode: "timetrial", laps: 2, field: [], tier: 4, time: "dusk", goal: { type: "time", max: 38.5 } },
      reward: { car: "phantom", text: "The Phantom LMP1 unlocks early." } },
    { id: "ru-canal", from: "benny", rep: 100, text: "There's a canal-side drift jam in Old Town when it rains. Benny takes bets.",
      event: { id: "x-canal", district: "oldtown", title: "Canal Drift Jam", track: "oldtown", mode: "drift", laps: 2, field: [], tier: 3, time: "night", weather: "rain", goal: { type: "drift", min: 3000 } },
      reward: { money: 2500, text: "₭2,500 from Benny's book." } },
    { id: "ru-dawn", from: "otto", rep: 160, text: "Otto knows a dawn race up the switchbacks. Old champions only. He'll vouch for you.",
      event: { id: "x-dawn", district: "ridge", title: "Old Champions' Dawn Run", track: "ridge", mode: "circuit", laps: 3, field: ["otto", "valentina", "sora"], tier: 5, time: "dawn", goal: { type: "place", max: 1 } },
      reward: { car: "spectre", text: "The Spectre Hyper unlocks early." } },
  ];

  const ACHIEVEMENTS = {
    first_win: { name: "First Win", how: "Win any race." },
    podium10: { name: "Regular on the Podium", how: "Finish on the podium 10 times." },
    beat_dex: { name: "Ironclad Broken", how: "Beat Dex Varga in a rival race." },
    beat_mara: { name: "Through the Wall", how: "Beat Mara Quill in a rival race." },
    beat_benny: { name: "House Always Loses", how: "Beat Benny Kale in a rival race." },
    beat_sora: { name: "Solved", how: "Beat Sora Lind in a rival race." },
    beat_valentina: { name: "Dethroned", how: "Beat Valentina Corsa in a rival race." },
    all_districts: { name: "Port Kerbside Local", how: "Unlock every district." },
    new_car: { name: "Second Car", how: "Buy a car." },
    maxed: { name: "Fully Built", how: "Take any upgrade to level 3." },
    drifter: { name: "Sideways", how: "Score 8,000 points in one drift event." },
    clean_win: { name: "Not a Scratch", how: "Win a race with no contact." },
    rain_night: { name: "Night Rain", how: "Win at night in the rain." },
    champion: { name: "Series Champion", how: "Win a championship." },
    story: { name: "Kerbside Champion", how: "Win the Kerbside Grand Prix." },
    full_crew: { name: "The Whole Garage", how: "Recruit five crew members." },
    first_ally: { name: "From Rival to Friend", how: "Turn a rival into an ally." },
    every_ending: { name: "Every Road", how: "See three different endings (New Game+ counts)." },
    turf: { name: "Running the Streets", how: "Take over a district." },
    rumours: { name: "Ear to the Ground", how: "Win two secret events from rumours." },
    gold_all: { name: "Gold Standard", how: "Gold medal in every time trial track." },
    escape_artist: { name: "Escape Artist", how: "Escape a pursuit at heat 5." },
    first_escape: { name: "Clean Getaway", how: "Escape a police pursuit." },
    perfect_drag: { name: "Five Perfect Shifts", how: "Shift perfectly five times in one drag race." },
    iron: { name: "Iron Stint", how: "Win an endurance race." },
    fragile: { name: "Handle With Care", how: "Deliver with the cargo untouched." },
    knockout: { name: "Last One Standing", how: "Win a tournament." },
    high_roller: { name: "High Roller", how: "Win a wager of ₭2,500 or more." },
    contract: { name: "Signed and Delivered", how: "Complete a sponsor contract." },
    team_champ: { name: "Team Champions", how: "Win a team championship season." },
    new_game_plus: { name: "Once More, Faster", how: "Start New Game+." },
    collector: { name: "Collector", how: "Own ten cars." },
    every_class: { name: "C to S", how: "Own a car in every class." },
    full_garage: { name: "Full Garage", how: "Own every car in Port Kerbside." },
  };

  const MODES = {
    circuit: { name: "Circuit", blurb: "Full grid, multiple laps." },
    sprint: { name: "Sprint", blurb: "One flat-out lap." },
    elimination: { name: "Elimination", blurb: "Last car out at the end of each lap." },
    timetrial: { name: "Time Trial", blurb: "You and your ghost against the clock." },
    drift: { name: "Drift", blurb: "Hold slides for points; keep them going for a multiplier." },
    rival: { name: "Rival", blurb: "One on one." },
    pursuit: { name: "Pursuit", blurb: "The police are after you. Get out of sight and stay there." },
    drag: { name: "Drag", blurb: "Launch on the revs, shift near the top, straight line." },
    touge: { name: "Touge", blurb: "One on one: pull 66 m clear and it's over." },
    endurance: { name: "Endurance", blurb: "Long race. Tyres wear; stop in the pit box for fresh ones." },
    delivery: { name: "Delivery", blurb: "Checkpoints against the clock. Mind the cargo." },
    team: { name: "Team", blurb: "Two teams, points by finishing position." },
  };

  const api = { CARS, CLASS_COST, UPGRADES, AI_PARTS, TYRES, PRESETS, LOOK_KEYS, LOOKS, DRIVERS, CAST, CREW, RIVAL_LINES, ENDINGS, SPONSORS, DISTRICTS, PAR, CHAPTERS, SIDE, RIVAL_CHALLENGES, GRUDGE, ARCS, TURNING_POINTS, CHAMPIONSHIPS, TOURNAMENTS, POINTS, CONTRACTS, TEAM_LEVELS, ACH_REWARDS, TEAM_SEASON, SEASON_PRIZE, CREWS, ACHIEVEMENTS, MODES, TURF, WEEKDAYS, TURF_EVENTS, RUMORS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KerbsideData = api;
})(typeof self !== "undefined" ? self : globalThis);
