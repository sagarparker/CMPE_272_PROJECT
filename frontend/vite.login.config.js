import {defineConfig} from 'vite';
export default defineConfig({build:{outDir:'dist/assets',emptyOutDir:false,lib:{entry:'src/login-jungle.js',formats:['es'],fileName:()=> 'login-jungle.js'},minify:true}});
