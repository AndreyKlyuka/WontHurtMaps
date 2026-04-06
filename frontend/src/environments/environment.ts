export const environment = {
  production: false,
  googleMapsApiKey: (window as { __env?: { googleMapsApiKey?: string } }).__env?.googleMapsApiKey ?? '',
};
