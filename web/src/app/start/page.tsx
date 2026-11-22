import { redirect } from "next/navigation";

// "Start free" used to land here before self sign-up shipped (task 3.2); old links go on.
export default function Page() {
  redirect("/signup");
}
