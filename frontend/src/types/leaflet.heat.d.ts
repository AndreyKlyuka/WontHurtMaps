// eslint-disable-next-line @typescript-eslint/no-unused-vars
import * as L from 'leaflet';

declare module 'leaflet' {
  function heatLayer(latlngs: Array<[number, number] | [number, number, number]>, options?: HeatMapOptions): Layer;

  interface HeatMapOptions {
    minOpacity?: number;
    maxZoom?: number;
    max?: number;
    radius?: number;
    blur?: number;
    gradient?: Record<number, string>;
  }
}
