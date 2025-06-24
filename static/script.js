const allDrawn = new Set();

let giftLimits = {};

function loadGiftLimits() {
  fetch("/limits")
    .then((res) => res.json())
    .then((data) => {
      giftLimits = data;

      const giftSelect = document.getElementById("gift");
      giftSelect.innerHTML = ""; // Clear existing options

      // Populate the select element with updated gift options
      for (const [giftName, limit] of Object.entries(giftLimits)) {
        const option = document.createElement("option");
        option.value = giftName;
        option.textContent = giftName;
        giftSelect.appendChild(option);
      }

      const currentGift = giftSelect.value;
      document.getElementById("gift-limit").value = giftLimits[currentGift] || "";
    });
}

function updateState() {
  fetch("/state")
    .then((res) => res.json())
    .then((data) => {
      const recentTableBody = document.getElementById("recent-table-body");
      const resultList = document.getElementById("result");
      const giftCountsDiv = document.getElementById("gift-counts");

      // 초기화
      recentTableBody.innerHTML = "";
      resultList.innerHTML = "";
      allDrawn.clear();

      // 최근 추첨 결과 테이블
      data.result.forEach((entry) => {
        const row = document.createElement("tr");
        row.id = entry["NO"]; // 면허번호를 ID로 사용하여 중복 방지
        row.innerHTML = `
          <td>${entry["NO"]}</td>
          <td>${entry["이름"]}</td>
          <td>${entry["경품"]}</td>
          <td><button class="btn btn-sm btn-outline-warning" onclick='redrawEntry(${JSON.stringify(
            entry
          )})'>재추첨</button></td>
        `;

        recentTableBody.appendChild(row);
      });

      // 전체 누적 리스트
      data.all.forEach((entry) => {
        const key = `${entry["NO"]}_${entry["이름"]}_${entry["경품"]}`;
        if (!allDrawn.has(key)) {
          const li = document.createElement("li");
          li.className =
            "list-group-item d-flex justify-content-between align-items-center";
          li.innerHTML = `
            <span>${entry["NO"]} - ${entry["이름"]} - [${entry["경품"]}]</span>
            <button class="btn btn-sm btn-outline-danger" onclick='deleteEntry(${JSON.stringify(
              entry
            )})'>🗑</button>
          `;
          resultList.appendChild(li);
          allDrawn.add(key);
        }
      });

      // 남은 인원 및 총 당첨자 수
      document.getElementById("remaining").textContent = data.remaining;
      document.getElementById("total-winners").textContent = data.total;

      // ✅ 경품별 당첨자 수 표시
      const giftCounts = data.gift_counts || {};
      giftCountsDiv.innerHTML = Object.entries(giftCounts)
        .map(([gift, count]) => `${gift}: ${count}명`)
        .join(" &nbsp;&nbsp;•&nbsp;&nbsp; ");
    });
}

function deleteEntry(entry) {
  const confirmed = confirm(
    `정말로 삭제하시겠습니까?\n${entry["NO"]} - ${entry["이름"]} - [${entry["경품"]}]`
  );
  if (!confirmed) return;

  fetch(`/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  }).then(updateState);
}

function launchConfetti() {
  confetti({
    particleCount: 150,
    spread: 120,
    origin: { y: 0.6 },
  });
}

function draw() {
  const count = document.getElementById("count").value;
  const gift = document.getElementById("gift").value;
  const errorBox = document.getElementById("error");
  const limit = document.getElementById("gift-limit").value;
  errorBox.classList.add("d-none");

  // ✅ 변경된 제한값을 클라이언트 giftLimits에도 반영
  if (gift && limit) {
    giftLimits[gift] = parseInt(limit);
  }

  fetch("/draw", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `count=${count}&gift=${encodeURIComponent(gift)}&limit=${limit}`,
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        errorBox.textContent = data.error;
        errorBox.classList.remove("d-none");
        return;
      }

      // ✅ 최근 추첨 결과 테이블 업데이트
      const recentTableBody = document.getElementById("recent-table-body");
      recentTableBody.innerHTML = "";

      // data.result는 이번에 추첨된 인원 리스트
      data.result.forEach((entry) => {
        const row = document.createElement("tr");
        row.innerHTML = `<td>${entry["NO"]}</td><td>${entry["이름"]}</td><td>${entry["경품"]}</td>`;
        recentTableBody.appendChild(row);
      });

      updateState();
      launchConfetti();

      // ✅ 서버에서 최신 giftLimits 다시 가져와 반영
      return fetch("/limits");
    })
    .then((res) => res.json())
    .then((limits) => {
      giftLimits = limits;
    });
}

function redrawEntry(entry) {
  const confirmed = confirm(
    `정말로 재추첨 하시겠습니까?\n${entry["NO"]} - ${entry["이름"]} - [${entry["경품"]}]`
  );
  if (!confirmed) return;
  // 1. 삭제 요청
  fetch(`/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  })
    .then((res) => res.json())
    .then((deleteResult) => {
      if (!deleteResult.success) {
        alert("삭제 실패: " + (deleteResult.error || "알 수 없는 오류"));
        return;
      }
      // 2. 삭제된 후 redraw 진행
      const params = new URLSearchParams();
      params.append("count", 1);
      params.append("gift", entry["경품"]);
      params.append("exclude", JSON.stringify(entry));

      return fetch("/draw", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: params.toString(),
      });
    })
    .then((res) => res.json())
    .then((data) => {
      if (!data || data.error) {
        alert(data?.error || "재추첨 중 오류 발생");
        return;
      }

      // deleteEntry(entry); // 기존 인원 삭제
      // 기존 행 삭제
      const targetRow = document.getElementById(entry["NO"]);
      if (targetRow) targetRow.remove();

      // 새로 당첨된 한 명만 추가
      const recentTableBody = document.getElementById("recent-table-body");
      data.result.forEach((newEntry) => {
        const row = document.createElement("tr");
        row.id = newEntry["NO"];
        row.innerHTML = `
          <td>${newEntry["NO"]}</td>
          <td>${newEntry["이름"]}</td>
          <td>${newEntry["경품"]}</td>
          <td><button class="btn btn-sm btn-outline-warning" onclick='redrawEntry(${JSON.stringify(
            newEntry
          )})'>재추첨</button></td>
        `;
        recentTableBody.appendChild(row);
      });

      fetch("/state")
        .then((res) => res.json())
        .then((data) => {
          const recentTableBody = document.getElementById("recent-table-body");
          const resultList = document.getElementById("result");
          const giftCountsDiv = document.getElementById("gift-counts");

          // 초기화
          resultList.innerHTML = "";
          allDrawn.clear();

          // 전체 누적 리스트
          data.all.forEach((entry) => {
            const key = `${entry["NO"]}_${entry["이름"]}_${entry["경품"]}`;
            if (!allDrawn.has(key)) {
              const li = document.createElement("li");
              li.className =
                "list-group-item d-flex justify-content-between align-items-center";
              li.innerHTML = `
            <span>${entry["NO"]} - ${entry["이름"]} - [${entry["경품"]}]</span>
            <button class="btn btn-sm btn-outline-danger" onclick='deleteEntry(${JSON.stringify(
              entry
            )})'>🗑</button>
          `;
              resultList.appendChild(li);
              allDrawn.add(key);
            }
          });

          // 남은 인원 및 총 당첨자 수
          document.getElementById("remaining").textContent = data.remaining;
          document.getElementById("total-winners").textContent = data.total;

          // ✅ 경품별 당첨자 수 표시
          const giftCounts = data.gift_counts || {};
          giftCountsDiv.innerHTML = Object.entries(giftCounts)
            .map(([gift, count]) => `${gift}: ${count}명`)
            .join(" &nbsp;&nbsp;•&nbsp;&nbsp; ");
        });

      // updateState();
      launchConfetti();
    });
}

function clearDrawn() {
  fetch("/clear", { method: "POST" }).then(updateState);
}

function resetAll() {
  fetch("/reset", { method: "POST" }).then(updateState);
}

document.addEventListener("DOMContentLoaded", () => {
  updateState();
  loadGiftLimits();
});

document.getElementById("gift").addEventListener("change", function () {
  const gift = this.value;
  if (giftLimits[gift]) {
    document.getElementById("gift-limit").value = giftLimits[gift];
  } else {
    document.getElementById("gift-limit").value = "";
  }
});
// Allow pressing Enter to trigger the draw
document.addEventListener("keydown", function (event) {
  if (event.key === "Enter") {
    event.preventDefault();
    draw();
  }
});
