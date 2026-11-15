import { Suspense } from "react";

import { Footer } from "@/components/ui/Footer";
import { LoginForm } from "@/features/auth/LoginForm";

export const metadata = { title: "Sign in · TradeLens" };

export default function Page() {
  return (
    <>
      <main className="auth-main">
        <Suspense>
          <LoginForm />
        </Suspense>
      </main>
      <Footer />
    </>
  );
}
