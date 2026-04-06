import { Injectable } from '@angular/core';
import { importLibrary, setOptions } from '@googlemaps/js-api-loader';

import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class GoogleMapsLoaderService {
  constructor() {
    setOptions({
      key: environment.googleMapsApiKey,
      v: 'weekly',
    });
  }

  async load(): Promise<void> {
    await importLibrary('maps');
    await importLibrary('visualization');
  }
}
