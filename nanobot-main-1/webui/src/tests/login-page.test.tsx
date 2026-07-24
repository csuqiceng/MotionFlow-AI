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

  it("username field starts with the default operator account", () => {
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} />);
    expect(
      (screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement).value,
    ).toBe("operator");
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

  it("switching tab selects that role's default account", () => {
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} />);
    const user = screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement;
    fireEvent.change(user, { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("tab", { name: /工程师|engineer/i }));
    expect(
      (screen.getByPlaceholderText(/用户名|username/i) as HTMLInputElement).value,
    ).toBe("admin");
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

  it("allows operator login when controller and AI diagnostics are unhealthy", () => {
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} preflight={{ ok: true, data: {
      controller: { state: "unhealthy", latency_ms: 1, reason: "controller_unavailable" },
      voice: { state: "unhealthy", latency_ms: 1, reason: "voice_unavailable" },
      ai: { state: "unhealthy", latency_ms: 1, reason: "ai_unavailable" },
    } }} />);
    fireEvent.change(screen.getByPlaceholderText(/username/i), { target: { value: "op" } });
    fireEvent.change(screen.getByPlaceholderText(/瀵嗙爜|password/i), { target: { value: "pw" } });
    expect(screen.getByRole("button", { name: /鐧诲綍|login|杩涘叆|enter|sign in/i })).toBeEnabled();
  });

  it("shows lower-machine state separately from the status probe duration", () => {
    render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} preflight={{ ok: true, data: {
      controller: { state: "healthy", latency_ms: 173 },
      voice: { state: "unhealthy", latency_ms: 1, reason: "voice_unavailable" },
      ai: { state: "unhealthy", latency_ms: 1, reason: "ai_unavailable" },
    } }} />);

    expect(screen.getByRole("heading", { name: /智能.*机械手.*控制|Intelligent.*Robotics.*Control/ })).toBeInTheDocument();
    expect(screen.getByText(/下位机已连接|Machine connected/)).toBeInTheDocument();
    expect(screen.getByText("173ms")).toBeInTheDocument();
    expect(screen.queryByText("{{latency}}ms")).not.toBeInTheDocument();
  });

  it("does not present a disconnected or simulated lower machine as connected", () => {
    const { rerender } = render(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} preflight={{ ok: true, data: {
      controller: { state: "unhealthy", latency_ms: 12, reason: "lower_machine_not_connected" },
      voice: { state: "unhealthy", latency_ms: 1, reason: "voice_unavailable" },
      ai: { state: "unhealthy", latency_ms: 1, reason: "ai_unavailable" },
    } }} />);

    expect(screen.getByText(/下位机未连接|Machine not connected/)).toBeInTheDocument();
    expect(screen.queryByText(/下位机已连接|Machine connected/)).not.toBeInTheDocument();

    rerender(<LoginPage bootstrapOk={true} error={null} onSubmit={vi.fn()} preflight={{ ok: true, data: {
      controller: { state: "unhealthy", latency_ms: 12, reason: "simulation_mode" },
      voice: { state: "unhealthy", latency_ms: 1, reason: "voice_unavailable" },
      ai: { state: "unhealthy", latency_ms: 1, reason: "ai_unavailable" },
    } }} />);
    expect(screen.getByText(/模拟模式|Simulation mode/)).toBeInTheDocument();
  });
});
