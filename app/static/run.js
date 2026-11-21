const form = document.querySelector('#run-form');
const feedback = document?.querySelector('#run-feedback');
const submit = form?.querySelector('button[type="submit"]');

document.querySelector('#print')?.addEventListener('click', () => window.print());

form?.addEventListener('submit', async (event) => {
  event.preventDefault();
  delete feedback.dataset.error;
  feedback.value = '正在结算…';
  submit.disabled = true;
  try {
    const response = await fetch(form.action, {method: 'POST', body: new FormData(form)});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '结算失败，请重试。');
    window.location.assign(payload.location);
  } catch (error) {
    feedback.dataset.error = '';
    feedback.value = error.message || '请求失败，请重试。';
    submit.disabled = false;
  }
});

const claimForm = document.querySelector('#claim-form');
const claimFeedback = claimForm?.querySelector('#claim-feedback');
const claimSubmit = claimForm?.querySelector('button[type="submit"]');

claimForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  claimFeedback.dataset.error = '';
  claimFeedback.value = '正在生成认领…';
  claimSubmit.disabled = true;
  try {
    const response = await fetch(claimForm.action, {method: 'POST', body: new FormData(claimForm)});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || '认领失败，请重试。');
    window.location.assign(payload.location);
  } catch (error) {
    claimFeedback.dataset.error = '';
    claimFeedback.value = error.message || '请求失败，请重试。';
    claimSubmit.disabled = false;
  }
});
