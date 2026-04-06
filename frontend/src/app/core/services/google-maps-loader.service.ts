import { Injectable } from '@angular/core';
import { setOptions, importLibrary } from '@googlemaps/js-api-loader';

import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class GoogleMapsLoaderService {
  constructor() {
    setOptions({
      key: environment.googleMapsApiKey,
      v: 'weekly',
      libraries: ['visualization'],
    });
  }

  async load(): Promise<google.maps.VisualizationLibrary> {
    return await importLibrary('visualization');
  }
}
