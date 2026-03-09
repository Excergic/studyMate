import type { NextFetchEvent } from "next/server";
import { NextResponse } from "next/server";

const isPlaceholderClerkKey =
  !process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ||
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY === "pk_test_placeholder";

export async function middleware(
  request: Request,
  event: NextFetchEvent
) {
  if (isPlaceholderClerkKey) {
    return NextResponse.next();
  }
  const { clerkMiddleware, createRouteMatcher } = await import(
    "@clerk/nextjs/server"
  );
  const isPublicRoute = createRouteMatcher(["/sign-in(.*)", "/sign-up(.*)"]);
  const clerkMw = clerkMiddleware((auth, req: Request) => {
    if (!isPublicRoute(req)) {
      auth.protect();
    }
  });
  return clerkMw(request, event);
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
