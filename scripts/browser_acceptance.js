async (page) => {
  const baseUrl =
    (typeof process !== "undefined" && process.env.TUTOR_BASE_URL) ||
    "http://127.0.0.1:8020";
  const teacherToken = "evidence-teacher";
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };

  page.setDefaultTimeout(15000);
  const context = page.context();
  await context.clearCookies();

  const student = page;
  await student.goto(`${baseUrl}/`);
  await student.locator('input[name="count"]').fill("abc");
  await student.getByRole("button", { name: "开始练习" }).click();
  await student.getByText("题量必须是 1-30 的整数").waitFor();

  await student.locator('input[name="count"]').fill("2");
  await student.getByRole("button", { name: "开始练习" }).click();
  await student.waitForURL("**/waiting");
  await student.getByText("已提交给老师审核").waitFor();
  const sessionId = (await context.cookies(baseUrl)).find(
    (cookie) => cookie.name === "thread_id"
  )?.value;
  assert(sessionId, "未找到当前学生 session_id");

  const teacherContext = await context.browser().newContext();
  const teacher = await teacherContext.newPage();
  teacher.setDefaultTimeout(15000);
  await teacher.goto(`${baseUrl}/teacher/login`);
  await teacher.locator('input[name="token"]').fill(teacherToken);
  await teacher.getByRole("button", { name: "进入老师工作台" }).click();
  await teacher.waitForURL("**/teacher/sessions");
  await teacher.getByText("待预审").first().waitFor();
  await teacher
    .locator(`a[href="/teacher/session/${sessionId}"]`)
    .click();
  await teacher.waitForURL("**/teacher/review");
  await teacher.getByText("组卷预审").waitFor();

  const firstCard = teacher.locator(".card").first();
  await firstCard.locator('input[name="a"]').fill("0");
  await firstCard.getByRole("button", { name: "保存并重新计算" }).click();
  await teacher.getByText(/不能为 0/).waitFor();

  await teacher.getByRole("button", { name: /全部通过，定稿开做/ }).click();
  await teacher.waitForURL("**/teacher/review-done");
  await teacher.getByText("题目预审完成").waitFor();

  const summary = await teacherContext.newPage();
  summary.setDefaultTimeout(15000);
  await summary.goto(`${baseUrl}/teacher/summary`);
  await summary.getByText("等待学生完成练习").waitFor();

  await student.goto(`${baseUrl}/waiting`);
  await student.waitForURL("**/answer/0");
  for (let index = 0; index < 2; index += 1) {
    await student.getByText(`第 ${index + 1} / 2 题`).waitFor();
    const firstTextInput = student.locator('input[type="text"]').first();
    assert(
      (await firstTextInput.getAttribute("autocomplete")) === "off",
      "作答输入未关闭浏览器历史补全"
    );
    await student
      .getByRole("button", { name: "这题不会，先跳过" })
      .click();
    await student.waitForURL(`**/answer/${index + 1}`);
  }

  await student.getByText("本次作答汇总").waitFor();
  await student.getByRole("button", { name: "提交给老师确认" }).click();
  await student.waitForURL("**/waiting-confirmation");
  await student.getByText("已提交给老师确认").waitFor();

  await summary.getByText("本次练习结果确认").waitFor();
  await summary.getByRole("button", { name: "暂不更新，仅保留记录" }).click();
  await summary.waitForURL("**/teacher/completed");
  await summary.getByText("会话处理完成").waitFor();

  await student
    .getByText("本次未更新学生画像")
    .waitFor({ timeout: 15000 });

  const mobile = await context.newPage();
  await mobile.setViewportSize({ width: 390, height: 844 });
  await mobile.goto(`${baseUrl}/`);
  const overflow = await mobile.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1
  );
  assert(!overflow, "手机首页出现横向滚动");
  assert(
    await mobile.getByRole("button", { name: "开始练习" }).isVisible(),
    "手机首页开始按钮不可见"
  );
  assert(
    await mobile.getByRole("link", { name: "我的练习记录" }).isVisible(),
    "手机首页历史入口不可见"
  );
  await mobile.getByRole("link", { name: "我的练习记录" }).click();
  await mobile.getByText("我的练习记录").waitFor();
  const historyOverflow = await mobile.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1
  );
  assert(!historyOverflow, "手机历史页出现横向滚动");

  await summary.close();
  await mobile.close();
  await teacherContext.close();
  return "browser acceptance passed";
}
