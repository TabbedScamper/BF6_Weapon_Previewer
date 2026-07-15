// Weapon Previewer config. Models live on the shared R2 bucket under the
// weapons/ prefix; localhost dev serves raw GLBs from the local staging drive
// via serve.py instead.
const LOCAL = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
export const CONFIG = {
  manifest: './data/manifest.json',
  modelsBase: LOCAL ? '/models/' : 'https://pub-45114dae448e4a059f488662e3d47b19.r2.dev/weapons/models/',
  skinsBase: LOCAL ? '/skins/' : 'https://pub-45114dae448e4a059f488662e3d47b19.r2.dev/weapons/skins/',
};
