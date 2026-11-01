import { defineRouteMiddleware } from "@astrojs/starlight/route-data";

export const onRequest = defineRouteMiddleware(async (context, next) => {
  const route = context.locals.starlightRoute;

  if (route.id === "404") {
    // This is Starlight's per-request route-data clone, not the content entry.
    route.entry.data.draft = false;
  }

  await next();
});
