import { inject, Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface LocationFeature {
  type: 'Feature';
  geometry: { type: string; coordinates: number[] };
  properties: LocationProperties;
}

export interface LocationProperties {
  id: number;
  post_id: number;
  address: string;
  street_name: string | null;
  geo_type: string;
  confidence: number;
  resolved: boolean;
  resolved_by: string | null;
  post_date: string | null;
  post_excerpt: string | null;
}

export interface LocationsResponse {
  type: 'FeatureCollection';
  features: LocationFeature[];
}

export interface HeatmapResponse {
  points: [number, number, number][];
}

export interface StatsResponse {
  total: number;
  today: number;
  this_week: number;
  this_month: number;
  by_geo_type: Record<string, number>;
}

export interface CityResponse {
  id: number;
  name: string;
  name_ru: string;
  bbox: { north: number; south: number; east: number; west: number };
  center: { lat: number; lng: number };
  default_zoom: number;
}

export interface DistrictFeature {
  type: 'Feature';
  geometry: { type: string; coordinates: number[][][] };
  properties: { id: number; name: string; city_id: number };
}

export interface DistrictsResponse {
  type: 'FeatureCollection';
  features: DistrictFeature[];
}

export interface RouteDangerLocation {
  id: number;
  address: string;
  confidence: number;
  geo_type: string;
  lat: number;
  lng: number;
  post_date: string | null;
}

export interface RouteCheckResponse {
  route: { type: 'LineString'; coordinates: [number, number][] };
  danger_locations: RouteDangerLocation[];
  danger_count: number;
}

@Injectable({ providedIn: 'root' })
export class MapApiService {
  private readonly http = inject(HttpClient);

  getLocations(params: {
    west?: number;
    south?: number;
    east?: number;
    north?: number;
    min_confidence?: number;
    date_from?: string;
    date_to?: string;
    geo_type?: string;
  }): Observable<LocationsResponse> {
    return this.http.get<LocationsResponse>('/api/locations', {
      params: this.buildParams(params),
    });
  }

  getHeatmap(params: {
    west?: number;
    south?: number;
    east?: number;
    north?: number;
    min_confidence?: number;
    date_from?: string;
    date_to?: string;
  }): Observable<HeatmapResponse> {
    return this.http.get<HeatmapResponse>('/api/heatmap', {
      params: this.buildParams(params),
    });
  }

  getStats(params: { min_confidence?: number }): Observable<StatsResponse> {
    return this.http.get<StatsResponse>('/api/stats', {
      params: this.buildParams(params),
    });
  }

  getCities(): Observable<CityResponse[]> {
    return this.http.get<CityResponse[]>('/api/cities');
  }

  getDistricts(cityId: number): Observable<DistrictsResponse> {
    return this.http.get<DistrictsResponse>('/api/districts', {
      params: new HttpParams().set('city_id', cityId),
    });
  }

  checkRoute(params: {
    origin_lat: number;
    origin_lng: number;
    dest_lat: number;
    dest_lng: number;
    radius_meters?: number;
    hours?: number;
    min_confidence?: number;
  }): Observable<RouteCheckResponse> {
    return this.http.get<RouteCheckResponse>('/api/route/check', {
      params: this.buildParams(params),
    });
  }

  private buildParams(obj: Record<string, unknown>): HttpParams {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(obj)) {
      if (value !== null && value !== undefined) {
        params = params.set(key, String(value));
      }
    }
    return params;
  }
}
