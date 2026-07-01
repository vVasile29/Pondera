import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Brain, Moon, Sun, Menu, X } from "lucide-react";

interface LayoutProps {
  children: React.ReactNode;
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dark, setDark] = useState(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("theme");
      if (stored === "dark") return true;
      if (stored === "light") return false;
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return false;
  });

  useEffect(() => {
    const root = document.documentElement;
    if (dark) {
      root.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      root.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  }, [dark]);

  const toggleDark = () => setDark((prev) => !prev);

  const navLinks = [
    { href: "/", label: "Home" },
    { href: "/decisions", label: "Decisions" },
    { href: "/metrics", label: "Metrics" },
  ];

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-14 items-center justify-between">
          <div className="flex items-center gap-6">
            <Link to="/" className="flex items-center gap-2 font-bold text-lg">
              <Brain className="h-6 w-6 text-primary" />
              <span>Optium</span>
            </Link>
            <nav className="hidden md:flex items-center gap-1">
              {navLinks.map((link) => (
                <Button
                  key={link.href}
                  variant={
                    location.pathname === link.href ? "secondary" : "ghost"
                  }
                  size="sm"
                  asChild
                >
                  <Link to={link.href}>{link.label}</Link>
                </Button>
              ))}
            </nav>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleDark}
              aria-label="Toggle theme"
            >
              {dark ? (
                <Sun className="h-5 w-5" />
              ) : (
                <Moon className="h-5 w-5" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setMobileOpen(!mobileOpen)}
              aria-label="Toggle menu"
            >
              {mobileOpen ? (
                <X className="h-5 w-5" />
              ) : (
                <Menu className="h-5 w-5" />
              )}
            </Button>
          </div>
        </div>

        {mobileOpen && (
          <nav className="md:hidden border-t px-4 py-3 space-y-1">
            {navLinks.map((link) => (
              <Button
                key={link.href}
                variant={
                  location.pathname === link.href ? "secondary" : "ghost"
                }
                size="sm"
                className="w-full justify-start"
                asChild
                onClick={() => setMobileOpen(false)}
              >
                <Link to={link.href}>{link.label}</Link>
              </Button>
            ))}
          </nav>
        )}
      </header>

      <main className="flex-1 container py-6">{children}</main>

      <footer className="border-t py-6">
        <div className="container flex flex-col items-center gap-1 text-center text-sm text-muted-foreground">
          <p className="font-semibold">
            Optium — Multi-Criteria Decision Analysis
          </p>
          <p>
            Structured MCDA workflows for comparing, diagnosing, and ranking
            options.
          </p>
        </div>
      </footer>
    </div>
  );
}
