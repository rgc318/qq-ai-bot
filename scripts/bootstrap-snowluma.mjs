import fs from 'node:fs';
import path from 'node:path';

const source = '/deployment-secrets/onebot.json';
const configDirectory = '/app/data/config';
const target = path.join(configDirectory, 'onebot.json');
const desired = JSON.parse(fs.readFileSync(source, 'utf8'));
if (desired.networks?.wsClients?.[0]?.url !== 'ws://astrbot:6199/ws') {
  throw new Error('Unexpected reverse WebSocket destination');
}
fs.mkdirSync(configDirectory, { recursive: true });
if (fs.existsSync(target)) {
  fs.copyFileSync(target, `${target}.before-deployment-${Date.now()}.bak`);
}
fs.writeFileSync(target, `${JSON.stringify(desired, null, 2)}\n`, { mode: 0o600 });
console.log('SnowLuma global OneBot reverse WebSocket configuration written; token not printed.');
