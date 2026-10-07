/* Тир Пафнутия — отрисовка и управление (three.js).
 *
 * Правила (скорость, урон, сложность, расписание, раскрытие перевода) — в
 * shooter_rules.js, план волн — с сервера (/api/shooter/plan). Здесь — мир
 * на вершине Вавилонской башни, паук Пафнутий от третьего лица, слова-
 * противники, паутина, интерфейс поверх поля и экраны победы и поражения.
 *
 * Слово-противник — табличка с английским словом на маленьких ножках. После
 * попадания табличка переворачивается и показывает немецкий перевод, а потом
 * улетает вверх. Мини-босс держит много попаданий, и с каждым из них на нём
 * проступает немецкое слово.
 */

import * as THREE from './vendor/three.module.min.js';

const R = window.ShooterRules;
const $ = (id) => document.getElementById(id);
const LINES = JSON.parse($('shooter-lines').textContent);
const DEBUG = new URLSearchParams(location.search).has('debug');

const PALETTE = {
  swarm: { bg: '#f3e2a2', ink: '#4a3b12', border: '#b08b2e' },
  walker: { bg: '#f6efe2', ink: '#24304a', border: '#8a6a3a' },
  gunner: { bg: '#efc1b4', ink: '#6b1d14', border: '#a8432f' },
  boss: { bg: '#24304a', ink: '#f2c46b', border: '#f2c46b' },
  german: { bg: '#d7efc8', ink: '#1d4a29', border: '#4f8a3a' },
};

/* ================================================================================
 * звук: несколько синтезированных щелчков, без файлов
 * ================================================================================ */

class Sound {
  constructor() {
    this.ctx = null;
    this.on = true;
  }

  ensure() {
    if (!this.ctx) {
      try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { this.on = false; }
    }
  }

  tone(freq, duration, type = 'sine', volume = 0.04, slide = 0) {
    if (!this.on) return;
    this.ensure();
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t);
    if (slide) osc.frequency.exponentialRampToValueAtTime(Math.max(40, freq + slide), t + duration);
    gain.gain.setValueAtTime(volume, t);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + duration);
    osc.connect(gain).connect(this.ctx.destination);
    osc.start(t);
    osc.stop(t + duration + 0.02);
  }

  shot() { this.tone(700, 0.08, 'triangle', 0.025, -400); }
  hit() { this.tone(520, 0.12, 'sine', 0.05, 380); setTimeout(() => this.tone(880, 0.1, 'sine', 0.035), 60); }
  bossHit() { this.tone(220, 0.1, 'square', 0.03, 60); }
  hurt() { this.tone(160, 0.18, 'sawtooth', 0.04, -80); }
  net() { this.tone(300, 0.35, 'sine', 0.05, 500); }
  enemyShot() { this.tone(400, 0.07, 'square', 0.012, -150); }
  wave() { this.tone(392, 0.18, 'triangle', 0.05); setTimeout(() => this.tone(523, 0.25, 'triangle', 0.05), 170); }
  win() { [523, 659, 784, 1046].forEach((f, i) => setTimeout(() => this.tone(f, 0.3, 'triangle', 0.05), i * 160)); }
  lose() { [392, 330, 262].forEach((f, i) => setTimeout(() => this.tone(f, 0.35, 'sawtooth', 0.03), i * 220)); }
}

/* ================================================================================
 * текстуры, нарисованные на canvas
 * ================================================================================ */

function nextPow2(n) {
  let p = 64;
  while (p < n) p *= 2;
  return p;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Табличка со словом. Две строки — для мини-босса: английское слово и проступающий перевод. */
function wordCanvas(text, palette, subtitle = '') {
  const font = '700 76px Georgia, "Times New Roman", serif';
  const probe = document.createElement('canvas').getContext('2d');
  probe.font = font;
  const textWidth = Math.max(probe.measureText(text).width, subtitle ? probe.measureText(subtitle).width * 0.7 : 0);
  const width = Math.min(2048, nextPow2(textWidth + 70));
  const height = subtitle ? 256 : 128;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = palette.border;
  roundRect(ctx, 0, 0, width, height, 26);
  ctx.fill();
  ctx.fillStyle = palette.bg;
  roundRect(ctx, 7, 7, width - 14, height - 14, 21);
  ctx.fill();
  ctx.fillStyle = palette.ink;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const scale = Math.min(1, (width - 50) / Math.max(1, textWidth));
  ctx.font = `700 ${Math.floor(76 * scale)}px Georgia, "Times New Roman", serif`;
  if (subtitle) {
    ctx.fillText(text, width / 2, height * 0.32);
    ctx.font = `700 ${Math.floor(60 * scale)}px Georgia, "Times New Roman", serif`;
    ctx.fillStyle = '#9fe08a';
    ctx.fillText(subtitle, width / 2, height * 0.72);
  } else {
    ctx.fillText(text, width / 2, height / 2 + 3);
  }
  return { canvas, aspect: width / height };
}

function canvasTexture(canvas, renderer) {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return texture;
}

/** Плиты площадки с клинописными значками — вершина Вавилонской башни. */
function floorTexture(renderer) {
  const size = 1024;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const random = R.seeded(11);
  ctx.fillStyle = '#c9ad7f';
  ctx.fillRect(0, 0, size, size);
  const tile = size / 8;
  for (let y = 0; y < 8; y++) {
    for (let x = 0; x < 8; x++) {
      const shade = 190 + Math.floor(random() * 30);
      ctx.fillStyle = `rgb(${shade}, ${shade - 26}, ${shade - 70})`;
      ctx.fillRect(x * tile + 3, y * tile + 3, tile - 6, tile - 6);
      if (random() < 0.35) {
        ctx.strokeStyle = 'rgba(80, 55, 30, 0.45)';
        ctx.lineWidth = 3;
        for (let k = 0; k < 4; k++) {
          const cx = x * tile + 20 + random() * (tile - 40);
          const cy = y * tile + 20 + random() * (tile - 40);
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(cx + 10, cy + 4);
          ctx.lineTo(cx, cy + 8);
          ctx.closePath();
          ctx.stroke();
        }
      }
    }
  }
  const texture = canvasTexture(canvas, renderer);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(6, 6);
  return texture;
}

function brickTexture(renderer, base = '#a8784a') {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#7a5532';
  ctx.fillRect(0, 0, 256, 256);
  const random = R.seeded(5);
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 5; col++) {
      const offset = row % 2 ? 26 : 0;
      ctx.fillStyle = base;
      ctx.globalAlpha = 0.75 + random() * 0.25;
      ctx.fillRect(col * 52 + offset - 26, row * 32 + 2, 48, 28);
    }
  }
  ctx.globalAlpha = 1;
  const texture = canvasTexture(canvas, renderer);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  return texture;
}

/** Небо: сверху синее, к горизонту — тёплая пыльная дымка. */
function skyTexture(renderer) {
  const canvas = document.createElement('canvas');
  canvas.width = 16;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 512);
  gradient.addColorStop(0, '#3d6fa8');
  gradient.addColorStop(0.45, '#9cc0dd');
  gradient.addColorStop(0.62, '#f1dcb3');
  gradient.addColorStop(1, '#c8a46e');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 16, 512);
  return canvasTexture(canvas, renderer);
}

function softCircle(renderer, color = '255,255,255') {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  g.addColorStop(0, `rgba(${color},0.95)`);
  g.addColorStop(1, `rgba(${color},0)`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  return canvasTexture(canvas, renderer);
}

/** Паутина ловчей сети: радиальные нити и спираль. */
function webTexture(renderer) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 512;
  const ctx = canvas.getContext('2d');
  ctx.strokeStyle = 'rgba(255,255,255,0.95)';
  ctx.lineWidth = 3;
  for (let k = 0; k < 16; k++) {
    const a = (k / 16) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(256, 256);
    ctx.lineTo(256 + Math.cos(a) * 250, 256 + Math.sin(a) * 250);
    ctx.stroke();
  }
  for (let r = 24; r < 250; r += 22) {
    ctx.beginPath();
    for (let k = 0; k <= 16; k++) {
      const a = (k / 16) * Math.PI * 2;
      const x = 256 + Math.cos(a) * r;
      const y = 256 + Math.sin(a) * r;
      if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  return canvasTexture(canvas, renderer);
}

const letterCache = new Map();
function letterTexture(renderer, ch) {
  if (letterCache.has(ch)) return letterCache.get(ch);
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#b8321f';
  ctx.beginPath();
  ctx.arc(32, 32, 30, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#fff4e4';
  ctx.font = '700 40px Georgia, serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(ch, 32, 35);
  const texture = canvasTexture(canvas, renderer);
  letterCache.set(ch, texture);
  return texture;
}

/* ================================================================================
 * мир: вершина Вавилонской башни
 * ================================================================================ */

function buildWorld(scene, renderer) {
  const obstacles = [];
  scene.fog = new THREE.Fog(0xe2cfa6, 60, 260);

  const sky = new THREE.Mesh(new THREE.SphereGeometry(400, 32, 16),
    new THREE.MeshBasicMaterial({ map: skyTexture(renderer), side: THREE.BackSide, fog: false }));
  scene.add(sky);

  scene.add(new THREE.HemisphereLight(0xcfe0ff, 0x8a6a45, 1.15));
  const sun = new THREE.DirectionalLight(0xfff1d6, 1.9);
  sun.position.set(-30, 45, 20);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const cam = sun.shadow.camera;
  cam.left = cam.bottom = -40;
  cam.right = cam.top = 40;
  cam.near = 1;
  cam.far = 120;
  scene.add(sun);

  // площадка
  const floor = new THREE.Mesh(new THREE.CircleGeometry(R.ARENA_RADIUS + 2.5, 72),
    new THREE.MeshStandardMaterial({ map: floorTexture(renderer), roughness: 0.95 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  floor.userData.floor = true;
  scene.add(floor);

  // ярусы башни уходят вниз
  const bricks = brickTexture(renderer);
  for (let k = 0; k < 5; k++) {
    const radius = R.ARENA_RADIUS + 3 + k * 7;
    const tier = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius + 4, 10, 64, 1, true),
      new THREE.MeshStandardMaterial({ map: bricks.clone(), color: k % 2 ? 0xc49a68 : 0xb58758, roughness: 1 }));
    tier.material.map.repeat.set(radius / 1.5, 2);
    tier.material.map.needsUpdate = true;
    tier.position.y = -5 - k * 10;
    scene.add(tier);
    const ledge = new THREE.Mesh(new THREE.RingGeometry(radius - 0.5, radius + 7, 64),
      new THREE.MeshStandardMaterial({ color: 0xcfb07c, roughness: 1, side: THREE.DoubleSide }));
    ledge.rotation.x = -Math.PI / 2;
    ledge.position.y = -10 - k * 10 + 0.01;
    scene.add(ledge);
  }
  // пустыня далеко внизу и зиккураты на горизонте
  const desert = new THREE.Mesh(new THREE.CircleGeometry(390, 48),
    new THREE.MeshStandardMaterial({ color: 0xd2b27c, roughness: 1 }));
  desert.rotation.x = -Math.PI / 2;
  desert.position.y = -70;
  scene.add(desert);
  const random = R.seeded(23);
  for (let k = 0; k < 9; k++) {
    const angle = random() * Math.PI * 2;
    const distance = 160 + random() * 150;
    const group = new THREE.Group();
    for (let s = 0; s < 4; s++) {
      const w = 26 - s * 6;
      const step = new THREE.Mesh(new THREE.BoxGeometry(w, 6, w),
        new THREE.MeshStandardMaterial({ color: 0xbf9a64, roughness: 1 }));
      step.position.y = s * 6;
      group.add(step);
    }
    group.position.set(Math.cos(angle) * distance, -70, Math.sin(angle) * distance);
    group.scale.setScalar(0.6 + random() * 0.8);
    scene.add(group);
  }
  // облака ниже площадки
  const cloudTexture = softCircle(renderer);
  for (let k = 0; k < 26; k++) {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: cloudTexture, transparent: true, opacity: 0.55,
      depthWrite: false, fog: true }));
    const angle = random() * Math.PI * 2;
    const distance = 60 + random() * 160;
    sprite.position.set(Math.cos(angle) * distance, -18 - random() * 30, Math.sin(angle) * distance);
    sprite.scale.set(40 + random() * 40, 14 + random() * 10, 1);
    scene.add(sprite);
  }

  // парапет с шестью воротами и колоннами по бокам
  const wallMaterial = new THREE.MeshStandardMaterial({ map: bricks, color: 0xd8b98a, roughness: 0.95 });
  const segments = 72;
  for (let k = 0; k < segments; k++) {
    const angle = (k / segments) * Math.PI * 2;
    const nearGate = Array.from({ length: R.GATES }, (_, g) => (g / R.GATES) * Math.PI * 2 + Math.PI / R.GATES)
      .some((gateAngle) => Math.abs(Math.atan2(Math.sin(angle - gateAngle), Math.cos(angle - gateAngle))) < 0.11);
    if (nearGate) continue;
    const block = new THREE.Mesh(new THREE.BoxGeometry(2.7, 1.3, 0.8), wallMaterial);
    const radius = R.ARENA_RADIUS + 1.4;
    block.position.set(Math.cos(angle) * radius, 0.65, Math.sin(angle) * radius);
    block.rotation.y = -angle + Math.PI / 2;
    block.castShadow = block.receiveShadow = true;
    scene.add(block);
  }
  const columnMaterial = new THREE.MeshStandardMaterial({ color: 0xe9dcc0, roughness: 0.7 });
  const gold = new THREE.MeshStandardMaterial({ color: 0xc89b3c, roughness: 0.4, metalness: 0.6 });
  for (let g = 0; g < R.GATES; g++) {
    const gateAngle = (g / R.GATES) * Math.PI * 2 + Math.PI / R.GATES;
    for (const side of [-1, 1]) {
      const angle = gateAngle + side * 0.13;
      const radius = R.ARENA_RADIUS + 1.4;
      const column = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.65, 6, 16), columnMaterial);
      column.position.set(Math.cos(angle) * radius, 3, Math.sin(angle) * radius);
      column.castShadow = true;
      scene.add(column);
      const capital = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.4, 1.6), gold);
      capital.position.set(column.position.x, 6.1, column.position.z);
      scene.add(capital);
    }
    const arch = new THREE.Mesh(new THREE.TorusGeometry(2.05, 0.28, 8, 24, Math.PI), gold);
    const radius = R.ARENA_RADIUS + 1.4;
    arch.position.set(Math.cos(gateAngle) * radius, 6.2, Math.sin(gateAngle) * radius);
    arch.rotation.y = -gateAngle + Math.PI / 2;
    scene.add(arch);
  }

  // укрытия: стопки книг-словарей и глиняные таблички
  const bookColors = [0x7a2e24, 0x24304a, 0x3f5d36, 0x8a6a3a, 0x4b2f5a];
  const spots = [[9, 4], [-8, 7], [-3, -10], [12, -9], [-14, -3], [4, 15], [17, 6], [-6, 18], [-18, 12], [2, -19]];
  spots.forEach(([x, z], index) => {
    if (index % 3 === 2) {
      const tablet = new THREE.Mesh(new THREE.BoxGeometry(2.4, 3.2, 0.5),
        new THREE.MeshStandardMaterial({ color: 0xa87c52, roughness: 1, map: floorTexture(renderer) }));
      tablet.position.set(x, 1.6, z);
      tablet.rotation.y = random() * Math.PI;
      tablet.castShadow = tablet.receiveShadow = true;
      scene.add(tablet);
      obstacles.push({ x, z, r: 1.5, h: 3.2, mesh: tablet });
      return;
    }
    const stack = new THREE.Group();
    let y = 0;
    for (let b = 0; b < 4 + (index % 3); b++) {
      const h = 0.35 + random() * 0.25;
      const book = new THREE.Mesh(new THREE.BoxGeometry(2.2 - b * 0.12, h, 1.6 - b * 0.06),
        new THREE.MeshStandardMaterial({ color: bookColors[(b + index) % bookColors.length], roughness: 0.8 }));
      book.position.y = y + h / 2;
      book.rotation.y = (random() - 0.5) * 0.5;
      book.castShadow = book.receiveShadow = true;
      stack.add(book);
      y += h;
    }
    stack.position.set(x, 0, z);
    scene.add(stack);
    obstacles.push({ x, z, r: 1.35, h: y, mesh: stack });
  });
  return { obstacles, floor };
}

/* ================================================================================
 * Пафнутий
 * ================================================================================ */

function buildSpider() {
  const group = new THREE.Group();
  const body = new THREE.Group();
  group.add(body);
  const skin = new THREE.MeshStandardMaterial({ color: 0x6d2c21, roughness: 0.55, metalness: 0.1 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x3d1812, roughness: 0.6 });
  const abdomen = new THREE.Mesh(new THREE.SphereGeometry(0.75, 24, 16), skin);
  abdomen.scale.set(1, 0.85, 1.25);
  abdomen.position.set(0, 1.05, -0.75);
  const thorax = new THREE.Mesh(new THREE.SphereGeometry(0.52, 24, 16), skin);
  thorax.position.set(0, 1.0, 0.35);
  const stripe = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.06, 8, 24), dark);
  stripe.position.copy(abdomen.position);
  stripe.rotation.y = Math.PI / 2;
  body.add(abdomen, thorax, stripe);
  // глаза: большие, самодовольные
  const white = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.3 });
  const black = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.2 });
  for (const side of [-1, 1]) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.17, 16, 12), white);
    eye.position.set(side * 0.2, 1.2, 0.78);
    const pupil = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 8), black);
    pupil.position.set(side * 0.2, 1.2, 0.93);
    const brow = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.05, 0.05), dark);
    brow.position.set(side * 0.2, 1.42, 0.82);
    brow.rotation.z = side * -0.35;
    body.add(eye, pupil, brow);
  }
  // восемь лап. Лапа строится по точкам в своей системе координат (x — от тела наружу, y — вверх):
  // сустав на головогруди → колено выше тела → кончик на земле. Каждый сегмент — цилиндр точно
  // между двумя точками, суставы прикрыты шарами, поэтому лапа нигде не отрывается от тела.
  const legs = [];
  const legMaterial = new THREE.MeshStandardMaterial({ color: 0x4a1e17, roughness: 0.6 });
  const up = new THREE.Vector3(0, 1, 0);
  const segment = (from, to, radiusFrom, radiusTo) => {
    const direction = new THREE.Vector3().subVectors(to, from);
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radiusTo, radiusFrom, direction.length(), 8), legMaterial);
    mesh.position.copy(from).addScaledVector(direction, 0.5);
    mesh.quaternion.setFromUnitVectors(up, direction.normalize());
    return mesh;
  };
  const joint = (at, radius) => {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 10, 8), legMaterial);
    mesh.position.copy(at);
    return mesh;
  };
  const hipHeight = thorax.position.y - 0.05;
  const hip = new THREE.Vector3(0, 0, 0);
  const knee = new THREE.Vector3(0.72, 0.58, 0);
  const foot = new THREE.Vector3(1.42, -hipHeight, 0);         // кончик лапы — на земле
  for (let k = 0; k < 8; k++) {
    const side = k < 4 ? -1 : 1;
    const index = k % 4;                                        // 0 — передняя пара, 3 — задняя
    const pivot = new THREE.Group();
    // суставы — по бокам головогруди, внутри её поверхности
    pivot.position.set(side * 0.34, hipHeight, thorax.position.z + 0.27 - index * 0.18);
    // ось x лапы смотрит в сторону бока (у правых — +x, у левых — −x), передние лапы веером вперёд,
    // задние — назад
    pivot.rotation.y = (side > 0 ? 0 : Math.PI) + (index - 1.5) * 0.5 * side;
    const outer = new THREE.Group();
    outer.add(joint(hip, 0.1), segment(hip, knee, 0.08, 0.065), joint(knee, 0.075),
      segment(knee, foot, 0.06, 0.03));
    pivot.add(outer);
    group.add(pivot);
    legs.push({ pivot, outer, side, phase: (index % 2 === 0) === (side > 0) ? 0 : Math.PI, base: pivot.rotation.y });
  }
  group.traverse((o) => { if (o.isMesh) { o.castShadow = true; } });
  let walk = 0;
  return {
    group,
    body,
    update(dt, speed, airborne) {
      walk += dt * (4 + speed * 1.6);
      const amount = Math.min(1, speed / 6);
      legs.forEach((leg) => {
        const swing = Math.sin(walk + leg.phase) * 0.35 * amount;
        const lift = Math.max(0, Math.cos(walk + leg.phase)) * 0.4 * amount;
        leg.pivot.rotation.y = leg.base + swing;
        leg.outer.rotation.z = lift + (airborne ? 0.35 : 0);
      });
      body.position.y = Math.abs(Math.sin(walk * 2)) * 0.06 * amount;
    },
  };
}

/* ================================================================================
 * противники
 * ================================================================================ */

class Enemy {
  constructor(game, data, position) {
    this.game = game;
    this.data = data;
    this.kind = data.kind;
    this.type = R.KINDS[this.kind];
    this.alive = true;
    this.dying = 0;
    this.maxHp = this.kind === 'boss' ? R.bossHp(data.hp, game.difficulty) : 1;
    this.hp = this.maxHp;
    this.cooldown = 1 + Math.random();
    this.volley = 0;
    this.strafe = Math.random() < 0.5 ? 1 : -1;
    this.time = Math.random() * 10;
    this.position = new THREE.Vector3(position[0], 0, position[1]);
    this.build();
  }

  build() {
    const scale = this.type.scale;
    const text = this.data.en;
    const palette = PALETTE[this.kind];
    const drawn = this.kind === 'boss'
      ? wordCanvas(text, palette, R.bossReveal(this.data.de, this.hp, this.maxHp))
      : wordCanvas(text, palette);
    this.texture = canvasTexture(drawn.canvas, this.game.renderer);
    const height = (this.kind === 'boss' ? 1.7 : 0.85) * scale;
    const width = Math.max(0.9, height * drawn.aspect * (this.kind === 'boss' ? 1 : 1));
    this.width = width;
    this.height = height;
    const side = new THREE.MeshStandardMaterial({ color: palette.border, roughness: 0.7 });
    this.face = new THREE.MeshStandardMaterial({ map: this.texture, roughness: 0.6 });
    this.materials = [side, side, side, side, this.face, this.face];
    this.block = new THREE.Mesh(new THREE.BoxGeometry(width, height, 0.28 * scale), this.materials);
    this.block.castShadow = true;
    this.lift = 0.55 * scale;
    this.block.position.y = this.lift + height / 2;
    this.group = new THREE.Group();
    this.group.add(this.block);
    // ножки
    this.legs = [];
    const legMaterial = new THREE.MeshStandardMaterial({ color: 0x2b2420, roughness: 0.8 });
    const count = this.kind === 'swarm' ? 2 : 4;
    for (let k = 0; k < count; k++) {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.05 * scale, 0.05 * scale, this.lift, 6), legMaterial);
      const x = (k / Math.max(1, count - 1) - 0.5) * width * 0.7;
      leg.position.set(x, this.lift / 2, 0);
      this.group.add(leg);
      this.legs.push(leg);
    }
    // пушка у глагола, корона у мини-босса
    if (this.kind === 'gunner' || this.kind === 'boss') {
      const metal = new THREE.MeshStandardMaterial({ color: this.kind === 'boss' ? 0xc89b3c : 0x3a3a40,
        roughness: 0.35, metalness: 0.7 });
      const base = new THREE.Mesh(new THREE.CylinderGeometry(0.22 * scale, 0.26 * scale, 0.2 * scale, 12), metal);
      base.position.y = this.lift + height + 0.1 * scale;
      this.barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.08 * scale, 0.1 * scale, 0.8 * scale, 10), metal);
      this.barrel.rotation.x = Math.PI / 2;
      this.barrel.position.set(0, this.lift + height + 0.22 * scale, 0.3 * scale);
      this.group.add(base, this.barrel);
    }
    if (this.kind === 'boss') {
      const crown = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.08, 8, 20),
        new THREE.MeshStandardMaterial({ color: 0xf2c46b, metalness: 0.8, roughness: 0.3, emissive: 0x332200 }));
      crown.rotation.x = Math.PI / 2;
      crown.position.y = this.lift + height + 0.75;
      this.crown = crown;
      this.group.add(crown);
    }
    this.group.position.copy(this.position);
    this.game.scene.add(this.group);
    this.radius = Math.max(0.55, width / 2);
  }

  get center() {
    return new THREE.Vector3(this.position.x, this.lift + this.height / 2, this.position.z);
  }

  redraw(german) {
    const drawn = german
      ? wordCanvas(german, PALETTE.german)
      : wordCanvas(this.data.en, PALETTE[this.kind], R.bossReveal(this.data.de, this.hp, this.maxHp));
    const old = this.texture;
    this.texture = canvasTexture(drawn.canvas, this.game.renderer);
    this.face.map = this.texture;
    this.face.needsUpdate = true;
    old.dispose();
  }

  hit(power = 1) {
    if (!this.alive) return false;
    this.hp -= power;
    this.flash = 0.15;
    if (this.hp > 0) {
      this.redraw(null);
      this.game.sound.bossHit();
      return false;
    }
    this.alive = false;
    this.dying = 1.6;
    this.redraw(this.data.de);
    this.game.onDefeat(this);
    return true;
  }

  update(dt) {
    this.time += dt;
    const game = this.game;
    if (!this.alive) {
      this.dying -= dt;
      const t = 1.6 - this.dying;
      this.block.rotation.y = Math.min(Math.PI, t * 9);
      if (t > 0.45) {
        this.group.position.y += dt * 2.6;
        const s = Math.max(0.01, 1 - (t - 0.45) * 0.7);
        this.group.scale.setScalar(s);
      }
      return this.dying > 0;
    }
    const player = game.player.position;
    const toPlayer = new THREE.Vector3(player.x - this.position.x, 0, player.z - this.position.z);
    const distance = toPlayer.length() || 0.001;
    toPlayer.divideScalar(distance);
    const speed = R.speed(this.kind, game.difficulty);
    const move = new THREE.Vector3();
    if (this.type.keep) {
      if (distance > this.type.keep + 1.5) move.add(toPlayer);
      else if (distance < this.type.keep - 2) move.sub(toPlayer);
      move.add(new THREE.Vector3(-toPlayer.z, 0, toPlayer.x).multiplyScalar(0.55 * this.strafe));
      if (Math.random() < dt * 0.3) this.strafe *= -1;
    } else if (distance > this.type.melee * 0.8) {
      move.add(toPlayer);
    }
    // расталкиваются друг с другом и обходят укрытия
    for (const other of game.enemies) {
      if (other === this || !other.alive) continue;
      const dx = this.position.x - other.position.x;
      const dz = this.position.z - other.position.z;
      const d2 = dx * dx + dz * dz;
      const limit = (this.radius + other.radius) * 0.9;
      if (d2 < limit * limit && d2 > 1e-6) {
        const d = Math.sqrt(d2);
        move.x += (dx / d) * (limit - d) * 1.5;
        move.z += (dz / d) * (limit - d) * 1.5;
      }
    }
    if (move.lengthSq() > 1) move.normalize();
    this.position.addScaledVector(move, speed * dt);
    game.pushOut(this.position, this.radius * 0.8);
    const clamped = R.clampToArena(this.position.x, this.position.z, this.radius);
    this.position.x = clamped[0];
    this.position.z = clamped[1];
    // смотрит на паука
    const yaw = Math.atan2(toPlayer.x, toPlayer.z);
    this.group.rotation.y += Math.atan2(Math.sin(yaw - this.group.rotation.y), Math.cos(yaw - this.group.rotation.y)) * Math.min(1, dt * 6);
    this.group.position.set(this.position.x, Math.abs(Math.sin(this.time * 7)) * 0.12, this.position.z);
    this.legs.forEach((leg, k) => { leg.rotation.x = Math.sin(this.time * 12 + k * Math.PI) * 0.4; });
    if (this.crown) this.crown.rotation.z += dt * 2;
    if (this.flash > 0) {
      this.flash -= dt;
      this.face.emissive = new THREE.Color(this.flash > 0 ? 0x553300 : 0x000000);
    }
    // атака: укус вплотную, выстрел издалека
    this.cooldown -= dt;
    if (this.cooldown > 0) return true;
    if (this.type.melee && distance <= this.type.melee + game.player.radius) {
      game.hurt(R.damage(this.kind, game.difficulty), this);
      this.cooldown = this.type.period;
      this.block.position.z = 0.3;
      setTimeout(() => { if (this.block) this.block.position.z = 0; }, 120);
      return true;
    }
    if (this.type.shootRange && distance <= this.type.shootRange) {
      const shots = this.kind === 'boss' ? this.type.volley : 1;
      for (let k = 0; k < shots; k++) {
        game.enemyShoot(this, (k - (shots - 1) / 2) * 0.12);
      }
      this.cooldown = this.kind === 'boss' ? this.type.volleyPeriod : this.type.period * (0.8 + Math.random() * 0.5);
    }
    return true;
  }

  dispose() {
    this.game.scene.remove(this.group);
    this.group.traverse((o) => {
      if (o.isMesh) {
        o.geometry.dispose();
        (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
      }
    });
    if (this.texture) this.texture.dispose();
  }
}

/* ================================================================================
 * игра
 * ================================================================================ */

class Game {
  constructor(data, options) {
    this.data = data;
    this.plan = data.plan;
    this.difficulty = options.difficulty;
    this.sensitivity = options.sensitivity;
    this.canvas = $('game-canvas');
    this.frame = $('game-frame');
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(70, 1, 0.1, 900);
    this.sound = new Sound();
    const world = buildWorld(this.scene, this.renderer);
    this.obstacles = world.obstacles;
    this.raycaster = new THREE.Raycaster();
    this.spider = buildSpider();
    this.scene.add(this.spider.group);
    this.webTexture = webTexture(this.renderer);
    this.glow = softCircle(this.renderer);
    this.keys = {};
    this.mouseDown = false;
    this.resize();
    this.bind();
    this.reset();
    this.last = performance.now();
    this.frameId = requestAnimationFrame((t) => this.loop(t));
  }

  /* --- состояние ------------------------------------------------------------ */

  reset() {
    (this.enemies || []).forEach((e) => e.dispose());
    (this.shots || []).forEach((s) => this.scene.remove(s.mesh));
    (this.enemyShots || []).forEach((s) => this.scene.remove(s.mesh));
    (this.flies || []).forEach((f) => this.scene.remove(f.mesh));
    (this.effects || []).forEach((f) => this.scene.remove(f.mesh));
    this.enemies = [];
    this.shots = [];
    this.enemyShots = [];
    this.flies = [];
    this.effects = [];
    this.player = {
      position: new THREE.Vector3(0, 0, 0), velocity: new THREE.Vector3(), yaw: Math.PI, pitch: 0.12,
      hp: R.PLAYER.hp, ammo: R.PLAYER.ammo, radius: R.PLAYER.radius, dash: 0, dashCooldown: 0,
      shotCooldown: 0, net: 0, airborne: false, hurt: 0,
    };
    this.defeated = {};
    this.stats = { shots: 0, hits: 0, kills: 0, damage: 0, time: 0 };
    this.waveIndex = -1;
    this.phase = 'ready';
    this.phaseTime = 0;
    this.queue = [];
    this.running = false;
    this.paused = false;
    this.ended = false;
    this.words = this.plan.waves.flatMap((w) => w.enemies.concat(w.boss ? [w.boss] : []));
    this.totalEnemies = this.words.length;
    this.buildDocument();
    this.updateHud(true);
    $('killfeed').innerHTML = '';
    $('hud-boss').hidden = true;
  }

  start() {
    this.running = true;
    this.paused = false;
    this.sound.ensure();
    $('overlay-start').hidden = true;
    this.nextWave();
    this.say('shooter_start');
  }

  /* --- волны ----------------------------------------------------------------- */

  nextWave() {
    this.waveIndex++;
    if (this.waveIndex >= this.plan.waves.length) {
      this.phase = 'done';
      this.phaseTime = 0;
      return;
    }
    const wave = this.plan.waves[this.waveIndex];
    const ordered = R.groupSwarms(wave.enemies);
    this.queue = R.spawnSchedule(ordered, this.difficulty, this.plan.seed * 31 + wave.number);
    this.waveLeft = wave.enemies.length + (wave.boss ? 1 : 0);
    this.phase = 'intro';
    this.phaseTime = 0;
    this.message(`Волна ${wave.number} из ${this.plan.waves.length}`, `${wave.size} слов · в конце — «${wave.boss.en}»`);
    this.sound.wave();
    if (wave.number > 1) this.say('shooter_wave', { wave: String(wave.number) });
  }

  updateWaves(dt) {
    this.phaseTime += dt;
    const level = R.DIFFICULTY[this.difficulty];
    if (this.phase === 'intro' && this.phaseTime >= R.WAVE_INTRO) {
      this.phase = 'fight';
      this.phaseTime = 0;
    } else if (this.phase === 'fight') {
      const alive = this.enemies.filter((e) => e.alive).length;
      while (this.queue.length && this.queue[0].t <= this.phaseTime && alive + 0 < level.maxAlive) {
        const item = this.queue.shift();
        this.spawn(item.enemy, R.gatePosition(item.gate));
        if (this.enemies.filter((e) => e.alive).length >= level.maxAlive) break;
      }
      if (this.queue.length && this.queue[0].t <= this.phaseTime) {
        // ждут, пока на поле освободится место
        this.queue.forEach((item) => { item.t += dt; });
      }
      if (!this.queue.length && !this.enemies.some((e) => e.alive && e.kind !== 'boss')) {
        const wave = this.plan.waves[this.waveIndex];
        this.phase = 'boss';
        this.phaseTime = 0;
        this.boss = this.spawn(wave.boss, R.gatePosition(Math.floor(Math.random() * R.GATES)));
        $('hud-boss').hidden = false;
        $('hud-boss-name').textContent = wave.boss.en;
        this.message('Мини-босс!', `«${wave.boss.en}» — ${this.boss.maxHp} попаданий`);
        this.say('shooter_boss', { word: wave.boss.en });
      }
    } else if (this.phase === 'boss' && this.boss && !this.boss.alive) {
      this.phase = 'cleared';
      this.phaseTime = 0;
      $('hud-boss').hidden = true;
      this.player.hp = Math.min(R.PLAYER.hp, this.player.hp + R.WAVE_HEAL);
      const last = this.waveIndex === this.plan.waves.length - 1;
      this.message(last ? 'Все волны отбиты!' : `Волна ${this.waveIndex + 1} пройдена`,
        last ? 'документ переведён' : `+${R.WAVE_HEAL} к прочности · передышка`);
    } else if (this.phase === 'cleared' && this.phaseTime >= R.WAVE_BREAK) {
      this.nextWave();
    } else if (this.phase === 'done' && this.phaseTime >= 1.0) {
      this.end(true);
    }
  }

  spawn(data, position) {
    const enemy = new Enemy(this, data, position);
    this.enemies.push(enemy);
    return enemy;
  }

  onDefeat(enemy) {
    const key = enemy.data.en.toLowerCase();
    this.defeated[key] = enemy.data.de;
    this.stats.kills++;
    this.waveLeft = Math.max(0, this.waveLeft - 1);
    this.sound.hit();
    this.feed(enemy.data.en, enemy.data.de, enemy.data.translated);
    this.translateDocument(key, enemy.data.de);
    if (enemy.kind === 'boss') {
      this.say('shooter_boss_down', { word: enemy.data.en, german: enemy.data.de });
      for (let k = 0; k < 2; k++) this.dropFly(enemy.position, k);
    } else if (Math.random() < R.FLY_CHANCE) {
      this.dropFly(enemy.position, 0);
    } else if (Math.random() < 0.12) {
      this.say('shooter_hit', { word: enemy.data.en, german: enemy.data.de }, false);
    }
    this.burst(enemy.center, enemy.kind === 'boss' ? 30 : 10);
  }

  /* --- игрок --------------------------------------------------------------------- */

  updatePlayer(dt) {
    const p = this.player;
    // направления — относительно камеры, которую поворачивает только мышь: W и ↑ — вперёд,
    // S и ↓ — назад, A и ← — влево, D и → — вправо. right — правая сторона экрана: камера смотрит
    // вдоль forward, её ось x — up × back = (−cos yaw, 0, sin yaw)
    const forward = new THREE.Vector3(Math.sin(p.yaw), 0, Math.cos(p.yaw));
    const right = new THREE.Vector3(-forward.z, 0, forward.x);
    const wish = new THREE.Vector3();
    if (this.keys.KeyW || this.keys.ArrowUp) wish.add(forward);
    if (this.keys.KeyS || this.keys.ArrowDown) wish.sub(forward);
    if (this.keys.KeyD || this.keys.ArrowRight) wish.add(right);
    if (this.keys.KeyA || this.keys.ArrowLeft) wish.sub(right);
    if (wish.lengthSq() > 0) wish.normalize();
    p.dashCooldown = Math.max(0, p.dashCooldown - dt);
    if (this.keys.ShiftLeft && p.dashCooldown <= 0 && wish.lengthSq() > 0) {
      p.dash = R.PLAYER.dashTime;
      p.dashCooldown = R.PLAYER.dashCooldown;
      this.dashDir = wish.clone();
    }
    let speed = R.PLAYER.speed;
    if (p.dash > 0) {
      p.dash -= dt;
      wish.copy(this.dashDir);
      speed = R.PLAYER.dashSpeed;
    }
    p.position.x += wish.x * speed * dt;
    p.position.z += wish.z * speed * dt;
    if (this.keys.Space && !p.airborne) {
      p.velocity.y = R.PLAYER.jump;
      p.airborne = true;
    }
    p.velocity.y -= R.PLAYER.gravity * dt;
    p.position.y += p.velocity.y * dt;
    if (p.position.y <= 0) {
      p.position.y = 0;
      p.velocity.y = 0;
      p.airborne = false;
    }
    this.pushOut(p.position, p.radius);
    const clamped = R.clampToArena(p.position.x, p.position.z, p.radius);
    p.position.x = clamped[0];
    p.position.z = clamped[1];
    p.ammo = R.regenAmmo(p.ammo, dt);
    p.shotCooldown = Math.max(0, p.shotCooldown - dt);
    p.net = Math.max(0, p.net - dt);
    p.hurt = Math.max(0, p.hurt - dt);
    // модель паука поворачивается туда, куда бежит (влево — влево), а без движения — туда, куда целится
    const group = this.spider.group;
    group.position.copy(p.position);
    const targetYaw = wish.lengthSq() > 0 ? Math.atan2(wish.x, wish.z) : p.yaw;
    group.rotation.y += Math.atan2(Math.sin(targetYaw - group.rotation.y), Math.cos(targetYaw - group.rotation.y)) * Math.min(1, dt * 10);
    this.spider.update(dt, wish.lengthSq() > 0 ? speed : 0, p.airborne);
    if (this.mouseDown && p.shotCooldown <= 0) this.shoot();
  }

  updateCamera() {
    const p = this.player;
    const distance = 6.2;
    const height = 2.6;
    const back = new THREE.Vector3(-Math.sin(p.yaw) * Math.cos(p.pitch), Math.sin(p.pitch), -Math.cos(p.yaw) * Math.cos(p.pitch));
    const target = new THREE.Vector3(p.position.x, p.position.y + 1.6, p.position.z);
    this.camera.position.copy(target).addScaledVector(back, distance).add(new THREE.Vector3(0, height * 0.35, 0));
    this.camera.position.y = Math.max(0.6, this.camera.position.y);
    const look = target.clone().addScaledVector(back, -8);
    this.camera.lookAt(look);
  }

  pushOut(position, radius) {
    for (const o of this.obstacles) {
      const dx = position.x - o.x;
      const dz = position.z - o.z;
      const limit = o.r + radius;
      const d2 = dx * dx + dz * dz;
      if (d2 < limit * limit && position.y < o.h) {
        const d = Math.sqrt(d2) || 0.001;
        position.x = o.x + (dx / d) * limit;
        position.z = o.z + (dz / d) * limit;
      }
    }
  }

  aimPoint() {
    this.raycaster.setFromCamera(new THREE.Vector2(0, 0), this.camera);
    const targets = this.enemies.filter((e) => e.alive).map((e) => e.block).concat(this.obstacles.map((o) => o.mesh));
    const hits = this.raycaster.intersectObjects(targets, true).filter((h) => h.distance > 4);
    if (hits.length) return hits[0].point;
    return this.raycaster.ray.at(80, new THREE.Vector3());
  }

  shoot() {
    const p = this.player;
    if (p.ammo < 1) return;
    p.ammo -= 1;
    p.shotCooldown = R.PLAYER.shotCooldown;
    this.stats.shots++;
    const origin = new THREE.Vector3(p.position.x, p.position.y + 1.25, p.position.z)
      .add(new THREE.Vector3(Math.sin(p.yaw), 0, Math.cos(p.yaw)).multiplyScalar(0.9));
    const direction = this.aimPoint().sub(origin).normalize();
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.16, 10, 8),
      new THREE.MeshBasicMaterial({ color: 0xffffff }));
    mesh.position.copy(origin);
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glow, transparent: true, depthWrite: false, opacity: 0.8 }));
    glow.scale.setScalar(0.9);
    mesh.add(glow);
    this.scene.add(mesh);
    // нить от паука к снаряду
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([origin, origin.clone()]),
      new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.7 }));
    this.scene.add(line);
    this.shots.push({ mesh, line, origin: origin.clone(), velocity: direction.multiplyScalar(R.PLAYER.shotSpeed), life: 1.6 });
    this.sound.shot();
  }

  throwNet() {
    const p = this.player;
    if (p.net > 0) return;
    p.net = R.PLAYER.netCooldown;
    const point = this.aimPoint();
    const center = new THREE.Vector3(point.x, 0.05, point.z);
    const toCenter = center.clone().sub(p.position);
    if (toCenter.length() > 22) center.copy(p.position).addScaledVector(toCenter.normalize(), 22);
    const mesh = new THREE.Mesh(new THREE.CircleGeometry(R.PLAYER.netRadius, 48),
      new THREE.MeshBasicMaterial({ map: this.webTexture, transparent: true, depthWrite: false, opacity: 0.95 }));
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.copy(center);
    mesh.scale.setScalar(0.1);
    this.scene.add(mesh);
    this.effects.push({ mesh, life: 1.4, kind: 'net' });
    this.sound.net();
    let caught = 0;
    for (const enemy of this.enemies) {
      if (!enemy.alive) continue;
      const d = Math.hypot(enemy.position.x - center.x, enemy.position.z - center.z);
      if (d <= R.PLAYER.netRadius + enemy.radius * 0.5) {
        enemy.hit(enemy.kind === 'boss' ? R.PLAYER.netBossDamage : 1);
        caught++;
      }
    }
    if (caught) this.message(`Сеть: ${caught}`, 'слов переведено разом', 1.4);
  }

  hurt(amount, source) {
    const p = this.player;
    if (this.ended) return;
    p.hp = Math.max(0, p.hp - amount);
    p.hurt = 0.35;
    this.stats.damage += amount;
    this.sound.hurt();
    this.frame.classList.remove('is-hurt');
    void this.frame.offsetWidth;
    this.frame.classList.add('is-hurt');
    if (Math.random() < 0.15) this.say('shooter_hurt', {}, false);
    if (p.hp < 30 && !this.lowSaid) {
      this.lowSaid = true;
      this.say('shooter_low');
    }
    if (p.hp <= 0) this.end(false);
  }

  enemyShoot(enemy, spread) {
    const origin = enemy.center.clone();
    origin.y += enemy.height * 0.45;
    const target = new THREE.Vector3(this.player.position.x, this.player.position.y + 1.0, this.player.position.z);
    const direction = target.sub(origin).normalize();
    direction.applyAxisAngle(new THREE.Vector3(0, 1, 0), spread);
    const letters = Array.from(enemy.data.en.replace(/[^A-Za-z]/g, '') || 'a');
    const ch = letters[Math.floor(Math.random() * letters.length)].toUpperCase();
    const mesh = new THREE.Sprite(new THREE.SpriteMaterial({ map: letterTexture(this.renderer, ch), depthWrite: false }));
    mesh.scale.setScalar(0.65);
    mesh.position.copy(origin);
    this.scene.add(mesh);
    const speed = enemy.type.shotSpeed * R.DIFFICULTY[this.difficulty].speed;
    this.enemyShots.push({ mesh, velocity: direction.multiplyScalar(speed), life: 3.5,
      damage: R.damage(enemy.kind, this.difficulty) * (enemy.kind === 'boss' ? 0.55 : 1) });
    this.sound.enemyShot();
  }

  dropFly(position, index) {
    const group = new THREE.Group();
    const body = new THREE.Mesh(new THREE.SphereGeometry(0.22, 12, 8), new THREE.MeshStandardMaterial({ color: 0x1b1b1b }));
    const wingMaterial = new THREE.MeshBasicMaterial({ color: 0xdff2ff, transparent: true, opacity: 0.7, side: THREE.DoubleSide });
    const wings = [];
    for (const side of [-1, 1]) {
      const wing = new THREE.Mesh(new THREE.CircleGeometry(0.28, 12), wingMaterial);
      wing.position.set(side * 0.25, 0.12, 0);
      wing.rotation.x = -Math.PI / 2;
      group.add(wing);
      wings.push(wing);
    }
    group.add(body);
    group.position.set(position.x + index * 0.8, 1.2, position.z + index * 0.5);
    this.scene.add(group);
    this.flies.push({ mesh: group, wings, time: 0 });
  }

  burst(center, count) {
    for (let k = 0; k < count; k++) {
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.glow, color: 0xffe9a8, transparent: true,
        depthWrite: false }));
      sprite.scale.setScalar(0.25 + Math.random() * 0.3);
      sprite.position.copy(center);
      this.scene.add(sprite);
      const v = new THREE.Vector3(Math.random() - 0.5, Math.random() * 0.9 + 0.3, Math.random() - 0.5).multiplyScalar(6);
      this.effects.push({ mesh: sprite, velocity: v, life: 0.8 + Math.random() * 0.4, kind: 'spark' });
    }
  }

  /* --- снаряды и эффекты ------------------------------------------------------------ */

  updateShots(dt) {
    this.shots = this.shots.filter((shot) => {
      const p0 = shot.mesh.position.clone();
      shot.mesh.position.addScaledVector(shot.velocity, dt);
      shot.velocity.y -= 2 * dt;
      shot.life -= dt;
      const p1 = shot.mesh.position;
      const positions = shot.line.geometry.attributes.position;
      positions.setXYZ(0, shot.origin.x, shot.origin.y, shot.origin.z);
      positions.setXYZ(1, p1.x, p1.y, p1.z);
      positions.needsUpdate = true;
      shot.line.material.opacity = Math.max(0, shot.life / 1.6) * 0.6;
      let done = shot.life <= 0 || p1.y < 0 || Math.hypot(p1.x, p1.z) > R.ARENA_RADIUS + 6;
      if (!done) {
        for (const enemy of this.enemies) {
          if (!enemy.alive) continue;
          const c = enemy.center;
          if (R.segmentHitsCylinder([p0.x, p0.y, p0.z], [p1.x, p1.y, p1.z], 0.16, [c.x, c.y, c.z],
            enemy.radius, enemy.height / 2)) {
            this.stats.hits++;
            enemy.hit(1);
            done = true;
            break;
          }
        }
      }
      if (!done) {
        for (const o of this.obstacles) {
          if (p1.y < o.h && Math.hypot(p1.x - o.x, p1.z - o.z) < o.r) { done = true; break; }
        }
      }
      if (done) {
        this.scene.remove(shot.mesh);
        this.scene.remove(shot.line);
        shot.mesh.geometry.dispose();
        shot.line.geometry.dispose();
      }
      return !done;
    });
    const p = this.player;
    this.enemyShots = this.enemyShots.filter((shot) => {
      shot.mesh.position.addScaledVector(shot.velocity, dt);
      shot.life -= dt;
      const pos = shot.mesh.position;
      let done = shot.life <= 0 || pos.y < 0;
      const dx = pos.x - p.position.x;
      const dy = pos.y - (p.position.y + 1.0);
      const dz = pos.z - p.position.z;
      if (!done && dx * dx + dy * dy + dz * dz < 1.0) {
        this.hurt(shot.damage);
        done = true;
      }
      if (!done) {
        for (const o of this.obstacles) {
          if (pos.y < o.h && Math.hypot(pos.x - o.x, pos.z - o.z) < o.r) { done = true; break; }
        }
      }
      if (done) this.scene.remove(shot.mesh);
      return !done;
    });
    this.flies = this.flies.filter((fly) => {
      fly.time += dt;
      fly.mesh.position.y = 1.2 + Math.sin(fly.time * 3) * 0.25;
      fly.mesh.rotation.y += dt * 2;
      fly.wings.forEach((w, k) => { w.rotation.z = Math.sin(fly.time * 40 + k * Math.PI) * 0.6; });
      const d = Math.hypot(fly.mesh.position.x - p.position.x, fly.mesh.position.z - p.position.z);
      if (d < 1.5) {
        p.hp = Math.min(R.PLAYER.hp, p.hp + R.FLY_HEAL);
        this.message('Муха!', `+${R.FLY_HEAL} к прочности`, 1.2);
        this.scene.remove(fly.mesh);
        return false;
      }
      return fly.time < 30;
    });
    this.effects = this.effects.filter((fx) => {
      fx.life -= dt;
      if (fx.kind === 'net') {
        const s = Math.min(1, (1.4 - fx.life) * 5);
        fx.mesh.scale.setScalar(s);
        fx.mesh.material.opacity = Math.min(0.95, fx.life);
      } else {
        fx.mesh.position.addScaledVector(fx.velocity, dt);
        fx.velocity.y -= 9 * dt;
        fx.mesh.material.opacity = Math.max(0, fx.life);
      }
      if (fx.life <= 0) {
        this.scene.remove(fx.mesh);
        return false;
      }
      return true;
    });
    this.enemies = this.enemies.filter((enemy) => {
      const keep = enemy.update(dt);
      if (!keep) enemy.dispose();
      return keep;
    });
  }

  /* --- интерфейс ----------------------------------------------------------------------- */

  buildDocument() {
    const box = $('doc-text');
    box.innerHTML = '';
    $('doc-title').textContent = this.data.title;
    this.docSpans = {};
    this.data.document.forEach((paragraph) => {
      const p = document.createElement('p');
      paragraph.forEach((token) => {
        const span = document.createElement('span');
        span.textContent = token.t;
        if (token.k) {
          span.className = 'dw';
          (this.docSpans[token.k] = this.docSpans[token.k] || []).push(span);
        }
        p.appendChild(span);
        if (token.s) p.appendChild(document.createTextNode(' '));
      });
      box.appendChild(p);
    });
  }

  translateDocument(key, german) {
    (this.docSpans[key] || []).forEach((span) => {
      span.textContent = german;
      span.className = 'dw done';
    });
  }

  feed(english, german, translated) {
    const list = $('killfeed');
    const item = document.createElement('li');
    item.innerHTML = '';
    const en = document.createElement('s');
    en.textContent = english;
    const de = document.createElement('b');
    de.textContent = german;
    item.append(en, ' → ', de);
    if (!translated) item.title = 'слова нет в словаре — осталось как есть';
    list.prepend(item);
    while (list.children.length > 6) list.lastChild.remove();
    setTimeout(() => item.classList.add('old'), 3500);
  }

  message(title, text = '', seconds = 2.6) {
    const box = $('hud-message');
    box.innerHTML = '';
    const h = document.createElement('b');
    h.textContent = title;
    box.appendChild(h);
    if (text) {
      const s = document.createElement('span');
      s.textContent = text;
      box.appendChild(s);
    }
    box.classList.remove('show');
    void box.offsetWidth;
    box.style.setProperty('--life', `${seconds}s`);
    box.classList.add('show');
  }

  say(occasion, fields = {}, important = true) {
    const variants = LINES[occasion] || [];
    const filled = variants.map((v) => v.replace(/\{(\w+)\}/g, (all, name) => (fields[name] !== undefined ? fields[name] : all)))
      .filter((v) => !/\{\w+\}/.test(v));
    if (!filled.length) return;
    const text = filled[Math.floor(Math.random() * filled.length)];
    const now = performance.now();
    if (!important && now - (this.lastSay || 0) < 4000) return;
    this.lastSay = now;
    $('speech-text').textContent = text;
    const speech = $('speech');
    speech.classList.remove('show');
    void speech.offsetWidth;
    speech.classList.add('show');
    if (window.Dragoman && !document.fullscreenElement) window.Dragoman.say(text);
  }

  updateHud(force) {
    const p = this.player;
    $('hud-hp').style.width = `${(100 * p.hp) / R.PLAYER.hp}%`;
    $('hud-hp-text').textContent = Math.ceil(p.hp);
    $('hud-ammo').style.width = `${(100 * p.ammo) / R.PLAYER.ammo}%`;
    $('hud-net').style.width = `${100 * (1 - p.net / R.PLAYER.netCooldown)}%`;
    const wave = this.plan.waves[Math.max(0, this.waveIndex)];
    $('hud-wave').textContent = `Волна ${Math.min(this.plan.waves.length, Math.max(1, this.waveIndex + 1))} / ${this.plan.waves.length}`;
    $('hud-left').textContent = this.waveIndex >= 0 ? `осталось слов: ${this.waveLeft}` : `слов в тексте: ${this.plan.words}`;
    const share = R.progress(this.defeated, this.words);
    $('hud-progress-bar').style.width = `${100 * share}%`;
    $('hud-progress-text').textContent = `переведено ${Math.round(100 * share)} % текста`;
    if (this.boss && this.boss.alive) {
      $('hud-boss-bar').style.width = `${(100 * this.boss.hp) / this.boss.maxHp}%`;
      $('hud-boss-name').textContent = `${this.boss.data.en} → ${R.bossReveal(this.boss.data.de, this.boss.hp, this.boss.maxHp)}`;
    }
    this.frame.classList.toggle('net-ready', p.net <= 0);
    void wave;
  }

  drawRadar() {
    const canvas = $('radar');
    const ctx = canvas.getContext('2d');
    const size = canvas.width;
    const half = size / 2;
    const range = 34;
    ctx.clearRect(0, 0, size, size);
    ctx.fillStyle = 'rgba(20, 26, 40, 0.55)';
    ctx.beginPath();
    ctx.arc(half, half, half - 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = 'rgba(242, 196, 107, 0.6)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    const p = this.player;
    const cos = Math.cos(p.yaw);
    const sin = Math.sin(p.yaw);
    const toRadar = (x, z) => {
      const dx = x - p.position.x;
      const dz = z - p.position.z;
      const rx = -(dx * cos - dz * sin);
      const ry = -(dx * sin + dz * cos);
      return [half + (rx / range) * half, half + (ry / range) * half];
    };
    // край площадки
    ctx.strokeStyle = 'rgba(255,255,255,0.25)';
    ctx.beginPath();
    for (let k = 0; k <= 48; k++) {
      const a = (k / 48) * Math.PI * 2;
      const [x, y] = toRadar(Math.cos(a) * R.ARENA_RADIUS, Math.sin(a) * R.ARENA_RADIUS);
      if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    const colors = { swarm: '#f3d36b', walker: '#f6efe2', gunner: '#ff7a5c', boss: '#f2c46b' };
    for (const enemy of this.enemies) {
      if (!enemy.alive) continue;
      const [x, y] = toRadar(enemy.position.x, enemy.position.z);
      if (Math.hypot(x - half, y - half) > half - 3) continue;
      ctx.fillStyle = colors[enemy.kind];
      ctx.beginPath();
      ctx.arc(x, y, enemy.kind === 'boss' ? 5 : 2.8, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(half, half - 7);
    ctx.lineTo(half - 5, half + 5);
    ctx.lineTo(half + 5, half + 5);
    ctx.closePath();
    ctx.fill();
  }

  /* --- конец боя ------------------------------------------------------------------------- */

  end(won) {
    if (this.ended) return;
    this.ended = true;
    this.running = false;
    if (document.pointerLockElement) document.exitPointerLock();
    const stats = this.stats;
    const share = R.progress(this.defeated, this.words);
    const stars = R.stars({ won, shots: stats.shots, hits: stats.hits, hp: this.player.hp });
    $('end-title').textContent = won ? 'Победа! Документ переведён' : 'Поражение: слова одолели паука';
    $('end-stats').textContent = `${'★'.repeat(stars)}${'☆'.repeat(3 - stars)} · время ${clock(stats.time)} · переведено слов: ` +
      `${stats.kills} из ${this.totalEnemies} (${Math.round(100 * share)} % текста) · точность ` +
      `${stats.shots ? Math.round((100 * stats.hits) / stats.shots) : 0} % · получено урона: ${Math.round(stats.damage)}`;
    const box = $('end-translation');
    box.innerHTML = '';
    if (won) {
      const title = document.createElement('h3');
      title.textContent = 'Перевод документа';
      box.appendChild(title);
      this.data.translation.forEach((paragraph) => {
        const p = document.createElement(paragraph.heading ? 'h4' : 'p');
        p.textContent = paragraph.text;
        box.appendChild(p);
      });
    } else {
      const title = document.createElement('h3');
      title.textContent = 'Что успели перевести';
      box.appendChild(title);
      box.appendChild($('doc-text').cloneNode(true));
    }
    $('end-export').href = this.data.export;
    $('end-open').href = this.data.link;
    $('overlay-end').className = `overlay overlay-end ${won ? 'is-win' : 'is-lose'}`;
    $('overlay-end').hidden = false;
    if (won) { this.sound.win(); this.say('shooter_win'); } else { this.sound.lose(); this.say('shooter_lose'); }
  }

  /* --- управление ----------------------------------------------------------------------------- */

  bind() {
    window.addEventListener('resize', () => this.resize());
    document.addEventListener('keydown', (e) => {
      if (!this.running && e.code !== 'Escape') {
        if (e.code === 'KeyM') this.sound.on = !this.sound.on;
        return;
      }
      if (['Space', 'Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code)) e.preventDefault();
      this.keys[e.code] = true;
      if (e.code === 'Tab') $('doc-panel').hidden = !$('doc-panel').hidden;
      if (e.code === 'KeyM') this.sound.on = !this.sound.on;
      if (e.code === 'KeyF') this.fullscreen();
      if (e.code === 'KeyE') this.throwNet();
    });
    document.addEventListener('keyup', (e) => { this.keys[e.code] = false; });
    this.canvas.addEventListener('mousedown', (e) => {
      if (!this.running || this.paused) return;
      if (document.pointerLockElement !== this.canvas) {
        lockPointer(this.canvas);
      }
      if (e.button === 0) { this.mouseDown = true; }
      if (e.button === 2) { this.throwNet(); }
    });
    this.canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    document.addEventListener('mouseup', (e) => { if (e.button === 0) this.mouseDown = false; });
    document.addEventListener('mousemove', (e) => {
      if (!this.running || this.paused) return;
      const locked = document.pointerLockElement === this.canvas;
      if (!locked && !e.buttons) return;       // без захвата мыши — поворот перетаскиванием
      const k = 0.0022 * this.sensitivity;
      this.player.yaw -= e.movementX * k;
      this.player.pitch = Math.max(-0.45, Math.min(0.75, this.player.pitch + e.movementY * k));
    });
    document.addEventListener('pointerlockchange', () => {
      if (document.pointerLockElement !== this.canvas && this.running && !this.ended && this.lockedOnce) this.pause(true);
      if (document.pointerLockElement === this.canvas) this.lockedOnce = true;
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && this.running && !this.ended) this.pause(true);
    });
  }

  fullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else this.frame.requestFullscreen && this.frame.requestFullscreen();
  }

  pause(value) {
    this.paused = value;
    this.keys = {};
    this.mouseDown = false;
    $('overlay-pause').hidden = !value;
    if (value) {
      $('pause-stats').textContent = `Волна ${this.waveIndex + 1} из ${this.plan.waves.length}, переведено слов: ` +
        `${this.stats.kills} из ${this.totalEnemies}.`;
      this.say('shooter_pause', {}, false);
    }
  }

  resize() {
    const width = this.frame.clientWidth;
    const height = this.frame.clientHeight;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
  }

  loop(now) {
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    if (this.running && !this.paused) {
      this.stats.time += dt;
      this.updatePlayer(dt);
      this.updateWaves(dt);
      this.updateShots(dt);
      this.updateHud();
      this.drawRadar();
    } else if (!this.running && !this.ended) {
      // пока ждём старта — облёт площадки
      this.player.yaw += dt * 0.15;
      this.spider.update(dt, 0, false);
    }
    this.updateCamera();
    this.renderer.render(this.scene, this.camera);
    this.frameId = requestAnimationFrame((t) => this.loop(t));
  }

  destroy() {
    cancelAnimationFrame(this.frameId);
    this.reset();
  }
}

function clock(seconds) {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/* ================================================================================
 * экран выбора текста
 * ================================================================================ */

let game = null;
let planData = null;

function planUrl() {
  const choice = $('shooter-text').value;
  const [kind, value] = choice.split(':');
  const waves = $('shooter-waves').value;
  return `/api/shooter/plan?${kind}=${encodeURIComponent(value)}&waves=${waves}`;
}

async function loadPlan() {
  $('shooter-status').textContent = 'Пафнутий переводит текст и расставляет слова…';
  $('shooter-start').disabled = true;
  try {
    const response = await fetch(planUrl());
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || response.statusText);
    planData = data;
    showPreview(data);
    $('shooter-status').textContent = '';
  } catch (problem) {
    planData = null;
    $('shooter-status').textContent = `Не удалось подготовить бой: ${problem.message}`;
  } finally {
    $('shooter-start').disabled = false;
  }
}

function showPreview(data) {
  const plan = data.plan;
  const box = $('shooter-preview');
  box.innerHTML = '';
  const summary = document.createElement('p');
  summary.textContent = `«${data.title}»: ${plan.words} разных слов (${plan.tokens} словоупотреблений). ` +
    `Волны: ${plan.waves.map((w) => w.size).join(' → ')}.`;
  box.appendChild(summary);
  const list = document.createElement('ol');
  list.className = 'boss-list';
  plan.waves.forEach((w) => {
    const li = document.createElement('li');
    li.textContent = `волна ${w.number}: ${w.size} слов, мини-босс «${w.boss.en}» → «${w.boss.de}» (${w.boss.hp} попаданий)`;
    list.appendChild(li);
  });
  box.appendChild(list);
}

let previewTimer = 0;
function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(loadPlan, 250);
}

$('shooter-waves').addEventListener('input', () => {
  $('shooter-waves-value').textContent = $('shooter-waves').value;
  schedulePreview();
});
$('shooter-text').addEventListener('change', schedulePreview);

$('shooter-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!planData) await loadPlan();
  if (!planData) return;
  $('shooter-setup').hidden = true;
  $('shooter-game').hidden = false;
  const options = { difficulty: $('shooter-difficulty').value, sensitivity: parseFloat($('shooter-sensitivity').value) };
  if (game) game.destroy();
  try {
    game = new Game(planData, options);
  } catch (problem) {
    $('shooter-setup').hidden = false;
    $('shooter-game').hidden = true;
    $('shooter-status').textContent = `Трёхмерная графика недоступна в этом браузере (${problem.message}).`;
    return;
  }
  $('overlay-start').hidden = false;
  $('overlay-end').hidden = true;
  $('overlay-pause').hidden = true;
  $('start-title').textContent = `«${planData.title}» — ${planData.plan.waves.length} волн`;
  $('game-frame').scrollIntoView({ behavior: 'smooth', block: 'center' });
  if (DEBUG) window.ShooterDebug = debugApi();
});

$('start-play').addEventListener('click', () => {
  if (!game) return;
  lockPointer(game.canvas);
  game.start();
});
$('resume').addEventListener('click', () => {
  if (!game) return;
  lockPointer(game.canvas);
  game.pause(false);
});
$('quit').addEventListener('click', () => { if (game) { game.pause(false); game.end(false); } });
$('end-again').addEventListener('click', () => {
  if (!game) return;
  $('overlay-end').hidden = true;
  game.reset();
  $('overlay-start').hidden = false;
});
$('end-setup').addEventListener('click', () => {
  if (game) game.destroy();
  game = null;
  $('shooter-game').hidden = true;
  $('shooter-setup').hidden = false;
});

// Захват мыши. Браузер может отказать (сразу после Esc, во фрейме, без окна) — тогда
// игра идёт и без захвата: поворот по перетаскиванию мышью.
function lockPointer(canvas) {
  if (!canvas.requestPointerLock) return;
  try {
    const request = canvas.requestPointerLock();
    if (request && request.catch) request.catch(() => {});
  } catch (problem) { /* без захвата */ }
}

function debugApi() {
  return {
    get game() { return game; },
    killAll() { game.enemies.filter((e) => e.alive).forEach((e) => { while (e.alive) e.hit(1); }); },
    spawnNow(n = 6) {
      game.queue.splice(0, n).forEach((item) => game.spawn(item.enemy, R.gatePosition(item.gate)));
    },
    skipWave() {
      game.queue.forEach((item) => game.spawn(item.enemy, R.gatePosition(item.gate)));
      game.queue = [];
      this.killAll();
    },
    win() {
      game.plan.waves.forEach((w) => w.enemies.concat([w.boss]).forEach((d) => {
        game.defeated[d.en.toLowerCase()] = d.de;
        game.translateDocument(d.en.toLowerCase(), d.de);
      }));
      game.stats.kills = game.totalEnemies;
      game.end(true);
    },
  };
}

schedulePreview();
