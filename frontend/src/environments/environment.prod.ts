export const environment = {
  production: true,
  googleMapsApiKey: (window as { __env?: { googleMapsApiKey?: string } }).__env?.googleMapsApiKey ?? '',
};
