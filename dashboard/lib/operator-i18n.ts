// Words for the operator screen, in Arabic (default) and English. The screen is right-to-left in Arabic.

export type Lang = "ar" | "en";

export const T = {
  title: { ar: "شاشة المشغّل", en: "Operator screen" },
  subtitle: {
    ar: "الطلبات التي تحتاج قرارك وطلبات اليوم، تتحدث تلقائياً كل 20 ثانية.",
    en: "Orders waiting for your decision and today's orders. Refreshes every 20 seconds.",
  },
  toReview: { ar: "طلبات بانتظار المراجعة", en: "Waiting for review" },
  nothingToReview: { ar: "لا توجد طلبات بانتظار المراجعة.", en: "Nothing needs review." },
  today: { ar: "طلبات اليوم", en: "Today's orders" },
  noOrders: { ar: "لا توجد طلبات اليوم بعد.", en: "No orders yet today." },
  approve: { ar: "موافقة", en: "Approve" },
  reject: { ar: "رفض", en: "Reject" },
  saveApprove: { ar: "حفظ وموافقة", en: "Save and approve" },
  edit: { ar: "تعديل الكميات", en: "Edit quantities" },
  cancel: { ar: "إلغاء", en: "Cancel" },
  customerSaid: { ar: "قال العميل", en: "Customer said" },
  match: { ar: "تطابق", en: "match" },
  total: { ar: "الإجمالي", en: "Total" },
  free: { ar: "مجاناً", en: "Free" },
  next: { ar: "الخطوة التالية", en: "Next step" },
  startPreparing: { ar: "بدء التجهيز", en: "Start preparing" },
  markDispatched: { ar: "تم الشحن", en: "Mark dispatched" },
  updated: { ar: "آخر تحديث", en: "Updated" },
  ai: { ar: "ذكاء اصطناعي", en: "AI" },
  language: { ar: "English", en: "العربية" },
  loading: { ar: "جارٍ التحميل…", en: "Loading…" },
  orders: { ar: "طلب", en: "orders" },
} satisfies Record<string, Record<Lang, string>>;

export const REASON: Record<string, Record<Lang, string>> = {
  insufficient_stock: { ar: "نقص في المخزون", en: "Short on stock" },
  credit: { ar: "حد الائتمان", en: "Credit check" },
  ai_review: { ar: "تحقق من طلب الذكاء الاصطناعي", en: "Check the AI's order" },
};

export const REVIEW_KIND: Record<string, Record<Lang, string>> = {
  low_confidence: { ar: "المنتج غير مؤكد", en: "Product not certain" },
  unusual_quantity: { ar: "كمية غير معتادة", en: "Unusual quantity" },
  shadow_mode: { ar: "الوضع الصامت: كل الطلبات تُراجع", en: "Shadow mode: every order is checked" },
};

export const STATUS: Record<string, Record<Lang, string>> = {
  pending: { ar: "جديد", en: "New" },
  confirmed: { ar: "مؤكد", en: "Confirmed" },
  preparing: { ar: "قيد التجهيز", en: "Preparing" },
  dispatched: { ar: "تم الشحن", en: "Dispatched" },
  delivered: { ar: "تم التسليم", en: "Delivered" },
  completed: { ar: "مكتمل", en: "Completed" },
  cancelled: { ar: "ملغي", en: "Cancelled" },
  failed: { ar: "فشل", en: "Failed" },
  requires_human_review: { ar: "بانتظار المراجعة", en: "Waiting for review" },
};

const LANG_KEY = "salesman_operator_lang";

export function savedLang(): Lang {
  try { return localStorage.getItem(LANG_KEY) === "en" ? "en" : "ar"; } catch { return "ar"; }
}
export function saveLang(lang: Lang) {
  try { localStorage.setItem(LANG_KEY, lang); } catch { /* storage unavailable: the choice lasts for this page */ }
}

export function money(amount: number | string, currency: string, lang: Lang) {
  const n = Number(amount);
  return lang === "ar"
    ? `${n.toLocaleString("ar-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency === "SAR" ? "ر.س" : currency}`
    : `${currency} ${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
