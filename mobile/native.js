import {Capacitor,registerPlugin,CapacitorHttp} from './vendor/capacitor.js';
export const native=Capacitor.isNativePlatform();
export const folder=native?registerPlugin('FolderLibrary'):null;
export function imageSource(uri){return Capacitor.convertFileSrc(uri)}
export async function nativeRequest(options){return CapacitorHttp.request(options)}
