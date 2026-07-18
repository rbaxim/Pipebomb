package main

/*
typedef void (*python_cb)(void);
typedef int (*gil_ensure_cb)(void);
typedef void (*gil_release_cb)(int);

static inline void call_python(python_cb cb, gil_ensure_cb ensure, gil_release_cb release) {
    int gstate = ensure();
    cb();
    release(gstate);
}
*/
import "C"
import (
	"sync"
	"unsafe"
)

type callbackEntry struct {
	callback   unsafe.Pointer
	gilEnsure  unsafe.Pointer
	gilRelease unsafe.Pointer
	canceled   *int32 // pointer to a C int32 in Python space
}

var (
	callbacks       = make(map[int]*callbackEntry)
	cancellationMap = make(map[int]bool)
	mapMu           sync.Mutex
	nextTaskId      int = 1
)

//export _StartGoTaskWithResult
func _StartGoTaskWithResult(callback unsafe.Pointer, taskId C.int, canceled *C.int, ensure unsafe.Pointer, release unsafe.Pointer) {
	id := int(taskId)

	entry := &callbackEntry{
		callback:   callback,
		gilEnsure:  ensure,
		gilRelease: release,
		canceled:   (*int32)(unsafe.Pointer(canceled)),
	}

	mapMu.Lock()
	cancellationMap[id] = false
	callbacks[id] = entry
	mapMu.Unlock()

	go func() {
		defer func() {
			mapMu.Lock()
			delete(cancellationMap, id)
			delete(callbacks, id)
			mapMu.Unlock()
		}()

		for {
			if *entry.canceled != 0 {
				return
			}

			C.call_python(
				(C.python_cb)(entry.callback),
				(C.gil_ensure_cb)(entry.gilEnsure),
				(C.gil_release_cb)(entry.gilRelease),
			)
			break
		}
	}()
}

//export _StartGoTask
func _StartGoTask(callback unsafe.Pointer, taskId C.int, ensure unsafe.Pointer, release unsafe.Pointer) {
	id := int(taskId)

	// sentinel: address of a static zero — never canceled
	var noCancel C.int = 0
	entry := &callbackEntry{
		callback:   callback,
		gilEnsure:  ensure,
		gilRelease: release,
		canceled:   (*int32)(unsafe.Pointer(&noCancel)),
	}

	mapMu.Lock()
	cancellationMap[id] = false
	callbacks[id] = entry
	mapMu.Unlock()

	go func() {
		defer func() {
			mapMu.Lock()
			delete(cancellationMap, id)
			delete(callbacks, id)
			mapMu.Unlock()
		}()

		C.call_python(
			(C.python_cb)(entry.callback),
			(C.gil_ensure_cb)(entry.gilEnsure),
			(C.gil_release_cb)(entry.gilRelease),
		)
	}()
}

//export _GetNextTaskId
func _GetNextTaskId() C.int {
	mapMu.Lock()
	id := nextTaskId
	nextTaskId++
	mapMu.Unlock()
	return C.int(id)
}

//export _CancelGoTask
func _CancelGoTask(taskId C.int) {
	mapMu.Lock()
	if entry, exists := callbacks[int(taskId)]; exists {
		entry.canceled = (*int32)(unsafe.Pointer(&[]int32{1}[0]))
	}
	cancellationMap[int(taskId)] = true
	mapMu.Unlock()
}

//export _IsCanceled
func _IsCanceled(taskId C.int) C.int {
	mapMu.Lock()
	canceled, exists := cancellationMap[int(taskId)]
	mapMu.Unlock()

	if !exists || canceled {
		return 1
	}
	return 0
}

func main() {}
