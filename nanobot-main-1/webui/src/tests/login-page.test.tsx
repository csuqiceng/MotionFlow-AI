import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { LoginPage } from "@/components/LoginPage";

// Project uses hash routing (window.location.hash), NOT react-router. happy-dom
// supports it natively. Do NOT import react-router/history.
function renderWithHash(hash: string) {
  window.location.hash = hash;
  return render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} />);
}

describe("LoginPage", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("default tab is operator when no hash", () => {
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} />);
    expect(screen.getByRole("tab", { name: /操作员|operator/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("#/engineer preselects engineer tab (URL priority over default operator)", () => {
    renderWithHash("#/engineer");
    expect(screen.getByRole("tab", { name: /工程师|engineer/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("username field starts empty (never prefilled)", () => {
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} />);
    expect(
      (screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement).value,
    ).toBe("");
  });

  it("submit disabled when username or password empty", () => {
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: /登录|login|进入|enter|sign in/i }),
    ).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/用户名|username/i), {
      target: { value: "u" },
    });
    expect(
      screen.getByRole("button", { name: /登录|login|进入|enter|sign in/i }),
    ).toBeDisabled(); // still empty password
  });

  it("switching tab clears username + password", () => {
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} />);
    const user = screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement;
    fireEvent.change(user, { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("tab", { name: /工程师|engineer/i }));
    expect(
      (screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement).value,
    ).toBe("");
  });

  it("bootstrap failed shows connection error and disables submit", () => {
    render(<LoginPage bootstrapOk={false} error={null} onSubmit={vi.fn()} />);
    expect(
      screen.getByText(/无法建立控制台连接|cannot establish/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /登录|login|进入|enter|sign in/i }),
    ).toBeDisabled();
  });

  it("401 shows generic credential error", () => {
    render(<LoginPage bootstrapOk={true} error={{ status: 401 }} onSubmit={vi.fn()} />);
    expect(
      screen.getByText(/用户名或密码错误|invalid credentials/i),
    ).toBeInTheDocument();
  });

  it("submit calls onSubmit with username+password+role", async () => {
    const onSubmit = vi.fn();
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={onSubmit} />);
    fireEvent.change(screen.getByPlaceholderText(/用户名|username/i), {
      target: { value: "op" },
    });
    fireEvent.change(screen.getByPlaceholderText(/密码|password/i), {
      target: { value: "pw" },
    });
    const btn = screen.getByRole("button", {
      name: /登录|login|进入|enter|sign in/i,
    });
    await act(async () => {
      fireEvent.click(btn);
    });
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          username: "op",
          password: "pw",
          role: expect.stringMatching(/operator|engineer/),
        }),
      ),
    );
  });
});
