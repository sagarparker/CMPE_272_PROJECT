import {mkdir,copyFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
await mkdir(root+'public/fonts',{recursive:true});
for(const weight of [400,500,600,700]) await copyFile(root+`node_modules/@fontsource/dm-sans/files/dm-sans-latin-${weight}-normal.woff2`,root+`public/fonts/dm-sans-latin-${weight}-normal.woff2`);
await copyFile(root+'node_modules/@fontsource/libre-baskerville/files/libre-baskerville-latin-400-normal.woff2',root+'public/fonts/libre-baskerville-latin-400-normal.woff2');
for(const name of ['dm-sans','libre-baskerville']) await copyFile(root+`node_modules/@fontsource/${name}/LICENSE`,root+`public/fonts/${name}-LICENSE.txt`);
